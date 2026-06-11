"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { signIn, signOut } from "next-auth/react";
import {
  AlertTriangle,
  CheckCircle2,
  Github,
  Loader2,
  LogOut,
  MessageSquareText,
  RefreshCw,
  Send,
  Star,
  Upload,
  X,
} from "lucide-react";

import type { StationReviewItem, StationReviewPage, StationReviewSummary } from "@/lib/types";
import { ERROR_REPORT_CATEGORIES, REVIEW_RATING_CHOICES, formatReviewSummary, ratingLabel, ratingToStars } from "@/lib/user-feedback";

interface StationFeedbackProviderProps {
  stationKey: string;
  stationLabel: string;
  initialReviewPage: StationReviewPage;
  children: ReactNode;
}

interface StationFeedbackContextValue {
  stationKey: string;
  stationLabel: string;
  reviewPage: StationReviewPage;
  viewer: StationReviewPage["viewer"];
  authChecking: boolean;
  openReportModal: (trigger?: HTMLElement | null) => void;
  openReviewModal: (trigger?: HTMLElement | null) => void;
  refreshFirstPage: () => Promise<void>;
  loadMoreReviews: () => Promise<void>;
  reviewsLoading: boolean;
}

const REVIEW_PAGE_SIZE = 10;

const StationFeedbackContext = createContext<StationFeedbackContextValue | null>(null);

function useStationFeedback() {
  const context = useContext(StationFeedbackContext);
  if (!context) {
    throw new Error("Station feedback components must be rendered inside StationFeedbackProvider.");
  }
  return context;
}

function statusClassName(tone: "success" | "error" | "info") {
  if (tone === "success") {
    return "feedback-status feedback-status-success";
  }
  if (tone === "error") {
    return "feedback-status feedback-status-error";
  }
  return "feedback-status";
}

function formatReviewDate(value: string) {
  if (!value) {
    return "";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function RatingStars({ value, size = 14 }: { value: number; size?: number }) {
  const selectedStars = ratingToStars(value) ?? 0;
  const label = ratingLabel(value);
  return (
    <span className="rating-stars" aria-label={label ? `${value} 分，${label}` : `${value} 分`}>
      {REVIEW_RATING_CHOICES.map((choice) => (
        <Star
          key={choice.stars}
          size={size}
          className={choice.stars <= selectedStars ? "rating-star-active" : ""}
          fill={choice.stars <= selectedStars ? "currentColor" : "none"}
        />
      ))}
    </span>
  );
}

function LoadingIcon({ size = 15 }: { size?: number }) {
  return <Loader2 size={size} className="spin-icon" aria-hidden="true" />;
}

function SummaryLine({ summary }: { summary: StationReviewSummary }) {
  const hasReviewScore = summary.reviewCount > 0 && summary.averageRating !== null;
  return (
    <div className="feedback-summary-line">
      <div>
        <span className={hasReviewScore ? "feedback-summary-value" : "feedback-summary-value feedback-summary-empty-value"}>{formatReviewSummary(summary)}</span>
        <span className="feedback-summary-label">用户评分</span>
      </div>
      <div>
        <span className="feedback-summary-value">{summary.reviewCount}</span>
        <span className="feedback-summary-label">公开评价</span>
      </div>
    </div>
  );
}

function mergeReviewPages(current: StationReviewPage, nextPage: StationReviewPage): StationReviewPage {
  const seen = new Set<number>();
  const reviews: StationReviewItem[] = [];
  for (const review of [...current.reviews, ...nextPage.reviews]) {
    if (seen.has(review.id)) {
      continue;
    }
    seen.add(review.id);
    reviews.push(review);
  }
  return {
    ...nextPage,
    reviews,
  };
}

function FeedbackModal({
  title,
  description,
  icon,
  children,
  onClose,
}: {
  title: string;
  description: string;
  icon: ReactNode;
  children: ReactNode;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    dialogRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="feedback-modal-overlay" role="presentation" onMouseDown={onClose}>
      <div
        ref={dialogRef}
        className="feedback-modal-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="feedback-modal-title"
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <button type="button" className="icon-button feedback-modal-close" onClick={onClose} aria-label="关闭弹窗">
          <X size={16} />
        </button>
        <div className="feedback-modal-head">
          <span className="feedback-modal-icon" aria-hidden="true">
            {icon}
          </span>
          <div>
            <h2 id="feedback-modal-title">{title}</h2>
            <p>{description}</p>
          </div>
        </div>
        <div className="feedback-modal-body">{children}</div>
      </div>
    </div>
  );
}

function FeedbackLoginPrompt({ checking = false, copy }: { checking?: boolean; copy: string }) {
  if (checking) {
    return (
      <div className="feedback-login-panel">
        <div>
          <h3>正在检查登录状态</h3>
          <p>正在同步 GitHub 登录状态和你的站点评价。</p>
        </div>
        <LoadingIcon />
      </div>
    );
  }

  return (
    <div className="feedback-login-panel">
      <div>
        <h3>需要 GitHub 登录</h3>
        <p>{copy}</p>
      </div>
      <button type="button" className="tiny-button feedback-login-button" onClick={() => signIn("github", { callbackUrl: window.location.href })}>
        <Github size={15} />
        使用 GitHub 登录
      </button>
    </div>
  );
}

function FeedbackUserbar() {
  const { viewer } = useStationFeedback();
  if (!viewer) {
    return null;
  }
  return (
    <div className="feedback-userbar">
      <div className="feedback-user">
        {viewer.avatarUrl ? <img src={viewer.avatarUrl} alt="" className="feedback-avatar" /> : null}
        <div>
          <p>{viewer.githubLogin}</p>
          <span>已登录 GitHub</span>
        </div>
      </div>
      <button type="button" className="tiny-button feedback-login-button" onClick={() => signOut({ callbackUrl: window.location.href })}>
        <LogOut size={14} />
        退出登录
      </button>
    </div>
  );
}

function ReportModalContent({ onClose }: { onClose: () => void }) {
  const { authChecking, stationKey, viewer } = useStationFeedback();
  const [reportStatus, setReportStatus] = useState<{ tone: "success" | "error" | "info"; message: string } | null>(null);
  const [reportSubmitting, setReportSubmitting] = useState(false);
  const [reportCategory, setReportCategory] = useState(ERROR_REPORT_CATEGORIES[0].value);
  const [reportDescription, setReportDescription] = useState("");
  const [reportFiles, setReportFiles] = useState<File[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const reportFileLabel = useMemo(() => {
    if (!reportFiles.length) {
      return "未选择截图";
    }
    return reportFiles.map((file) => file.name).join("、");
  }, [reportFiles]);

  function resetReportForm() {
    setReportCategory(ERROR_REPORT_CATEGORIES[0].value);
    setReportDescription("");
    setReportFiles([]);
    setReportStatus(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }

  async function submitReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!viewer || reportSubmitting) {
      return;
    }
    setReportSubmitting(true);
    setReportStatus({ tone: "info", message: "正在提交错误上报..." });
    try {
      const formData = new FormData();
      formData.set("station", stationKey);
      formData.set("category", reportCategory);
      formData.set("description", reportDescription);
      formData.set("currentUrl", window.location.href);
      for (const file of reportFiles) {
        formData.append("screenshots", file);
      }
      const response = await fetch("/api/station-error-reports", {
        method: "POST",
        headers: { accept: "application/json" },
        body: formData,
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(String(payload.error || "提交失败"));
      }
      setReportDescription("");
      setReportFiles([]);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      setReportStatus({ tone: "success", message: "错误上报已提交，感谢您的反馈，我们会在周末统一汇总处理。" });
    } catch (error) {
      setReportStatus({ tone: "error", message: error instanceof Error ? error.message : "错误上报提交失败。" });
    } finally {
      setReportSubmitting(false);
    }
  }

  if (!viewer) {
    return <FeedbackLoginPrompt checking={authChecking} copy="错误上报和截图上传需要登录后提交；如果 GitHub OAuth 未配置，页面会保留在这里并显示登录失败。" />;
  }

  if (reportStatus?.tone === "success") {
    return (
      <div className="feedback-success-panel">
        <CheckCircle2 size={22} />
        <div>
          <h3>上报已收到</h3>
          <p>{reportStatus.message}</p>
          <div className="feedback-modal-actions">
            <button type="button" className="tiny-button feedback-secondary-button" onClick={resetReportForm}>
              继续上报
            </button>
            <button type="button" className="tiny-button feedback-submit-button" onClick={onClose}>
              关闭
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      <FeedbackUserbar />
      <form className="feedback-form" onSubmit={submitReport}>
        <label className="feedback-field">
          <span>问题类型</span>
          <select value={reportCategory} onChange={(event) => setReportCategory(event.target.value as typeof reportCategory)} disabled={reportSubmitting}>
            {ERROR_REPORT_CATEGORIES.map((category) => (
              <option key={category.value} value={category.value}>
                {category.label}
              </option>
            ))}
          </select>
        </label>
        <label className="feedback-field">
          <span>错误说明</span>
          <textarea
            value={reportDescription}
            onChange={(event) => setReportDescription(event.target.value)}
            minLength={8}
            maxLength={2000}
            rows={5}
            disabled={reportSubmitting}
            placeholder="请说明哪里不对，例如分组倍率、充值档位、公告或排名指标。"
          />
        </label>
        <label className="feedback-file-button">
          <Upload size={15} />
          <span>选择截图</span>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            multiple
            disabled={reportSubmitting}
            onChange={(event) => setReportFiles(Array.from(event.currentTarget.files || []).slice(0, 3))}
          />
        </label>
        <p className="feedback-file-meta">{reportFileLabel} · 最多 3 张，单张 5MB，支持 PNG/JPEG/WebP。</p>
        {reportStatus ? (
          <p className={statusClassName(reportStatus.tone)}>
            {reportStatus.message}
          </p>
        ) : null}
        <div className="feedback-modal-actions">
          <button type="button" className="tiny-button feedback-secondary-button" onClick={onClose} disabled={reportSubmitting}>
            取消
          </button>
          <button type="submit" className="tiny-button feedback-submit-button" disabled={reportSubmitting}>
            {reportSubmitting ? <LoadingIcon /> : <Send size={15} />}
            {reportSubmitting ? "提交中" : "提交错误"}
          </button>
        </div>
      </form>
    </>
  );
}

function ReviewModalContent({ onClose }: { onClose: () => void }) {
  const { authChecking, stationKey, reviewPage, viewer, refreshFirstPage } = useStationFeedback();
  const [rating, setRating] = useState<number | null>(reviewPage.viewerReview?.rating ?? null);
  const [comment, setComment] = useState(reviewPage.viewerReview?.comment ?? "");
  const [reviewStatus, setReviewStatus] = useState<{ tone: "success" | "error" | "info"; message: string } | null>(null);
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const selectedStars = ratingToStars(rating) ?? 0;
  const selectedRatingLabel = ratingLabel(rating);

  useEffect(() => {
    setRating(reviewPage.viewerReview?.rating ?? null);
    setComment(reviewPage.viewerReview?.comment ?? "");
  }, [reviewPage.viewerReview]);

  async function submitReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!viewer || reviewSubmitting) {
      return;
    }
    if (rating === null) {
      setReviewStatus({ tone: "error", message: "请选择评分。" });
      return;
    }
    setReviewSubmitting(true);
    setReviewStatus({ tone: "info", message: "正在保存评价..." });
    try {
      const response = await fetch("/api/station-reviews", {
        method: "POST",
        headers: { "content-type": "application/json", accept: "application/json" },
        body: JSON.stringify({ station: stationKey, rating, comment }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(String(payload.error || "保存失败"));
      }
      setReviewStatus({ tone: "success", message: "评价已保存，可随时回来修改。" });
      await refreshFirstPage();
    } catch (error) {
      setReviewStatus({ tone: "error", message: error instanceof Error ? error.message : "评价保存失败。" });
    } finally {
      setReviewSubmitting(false);
    }
  }

  if (!viewer) {
    return <FeedbackLoginPrompt checking={authChecking} copy="评分和公开留言需要 GitHub 登录后提交；每个账号对同一站点只保留一条评价，可随时修改。" />;
  }

  return (
    <>
      <FeedbackUserbar />
      <form className="feedback-form" onSubmit={submitReview}>
        <fieldset className="feedback-rating-group" disabled={reviewSubmitting}>
          <legend>评分</legend>
          <div className="feedback-star-rating" role="radiogroup" aria-label="评分">
            {REVIEW_RATING_CHOICES.map((choice) => (
              <button
                key={choice.stars}
                type="button"
                className={choice.stars <= selectedStars ? "feedback-star-button feedback-star-button-active" : "feedback-star-button"}
                disabled={reviewSubmitting}
                aria-pressed={rating === choice.rating}
                aria-label={`${choice.stars} 星，${choice.label}，${choice.rating} 分`}
                title={`${choice.stars} 星 · ${choice.label}`}
                onClick={() => {
                  setRating(choice.rating);
                  setReviewStatus(null);
                }}
              >
                <Star size={24} fill={choice.stars <= selectedStars ? "currentColor" : "none"} />
              </button>
            ))}
            {selectedRatingLabel ? (
              <span className="feedback-rating-label" aria-live="polite">
                {selectedRatingLabel} · {rating} 分
              </span>
            ) : null}
          </div>
        </fieldset>
        <label className="feedback-field">
          <span>公开留言</span>
          <textarea
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={1000}
            rows={5}
            disabled={reviewSubmitting}
            placeholder="说说这个站点的稳定性、价格透明度或使用体验。"
          />
        </label>
        {reviewStatus ? (
          <p className={statusClassName(reviewStatus.tone)}>
            {reviewStatus.tone === "success" ? <CheckCircle2 size={14} /> : null}
            {reviewStatus.message}
          </p>
        ) : null}
        <div className="feedback-modal-actions">
          <button type="button" className="tiny-button feedback-secondary-button" onClick={onClose} disabled={reviewSubmitting}>
            取消
          </button>
          <button type="submit" className="tiny-button feedback-submit-button" disabled={reviewSubmitting || rating === null}>
            {reviewSubmitting ? <LoadingIcon /> : <Send size={15} />}
            {reviewSubmitting ? "保存中" : "保存评价"}
          </button>
        </div>
      </form>
    </>
  );
}

export function StationFeedbackProvider({ stationKey, stationLabel, initialReviewPage, children }: StationFeedbackProviderProps) {
  const [reviewPage, setReviewPage] = useState(initialReviewPage);
  const [modal, setModal] = useState<"report" | "review" | null>(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [reviewsLoading, setReviewsLoading] = useState(false);
  const triggerRef = useRef<HTMLElement | null>(null);

  const fetchReviewPage = useCallback(
    async (offset = 0) => {
      const response = await fetch(
        `/api/station-reviews?station=${encodeURIComponent(stationKey)}&limit=${REVIEW_PAGE_SIZE}&offset=${offset}`,
        {
          headers: { accept: "application/json" },
          cache: "no-store",
        },
      );
      if (!response.ok) {
        throw new Error("评价加载失败。");
      }
      return (await response.json()) as StationReviewPage;
    },
    [stationKey],
  );

  const refreshFirstPage = useCallback(async () => {
    const page = await fetchReviewPage(0);
    setReviewPage(page);
  }, [fetchReviewPage]);

  useEffect(() => {
    let cancelled = false;
    setAuthChecking(true);
    fetchReviewPage(0)
      .then((page) => {
        if (!cancelled) {
          setReviewPage(page);
        }
      })
      .catch(() => {
        // Keep the server-rendered public snapshot when the live session check fails.
      })
      .finally(() => {
        if (!cancelled) {
          setAuthChecking(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [fetchReviewPage]);

  const loadMoreReviews = useCallback(async () => {
    if (reviewsLoading || !reviewPage.pagination.hasMore || reviewPage.pagination.nextOffset === null) {
      return;
    }
    setReviewsLoading(true);
    try {
      const page = await fetchReviewPage(reviewPage.pagination.nextOffset);
      setReviewPage((current) => mergeReviewPages(current, page));
    } finally {
      setReviewsLoading(false);
    }
  }, [fetchReviewPage, reviewPage.pagination.hasMore, reviewPage.pagination.nextOffset, reviewsLoading]);

  function openModal(nextModal: "report" | "review", trigger?: HTMLElement | null) {
    triggerRef.current = trigger || null;
    setModal(nextModal);
  }

  const closeModal = useCallback(() => {
    setModal(null);
    window.setTimeout(() => triggerRef.current?.focus(), 0);
  }, []);

  const contextValue = useMemo<StationFeedbackContextValue>(
    () => ({
      stationKey,
      stationLabel,
      reviewPage,
      viewer: reviewPage.viewer,
      authChecking,
      openReportModal: (trigger) => openModal("report", trigger),
      openReviewModal: (trigger) => openModal("review", trigger),
      refreshFirstPage,
      loadMoreReviews,
      reviewsLoading,
    }),
    [authChecking, loadMoreReviews, refreshFirstPage, reviewPage, reviewsLoading, stationKey, stationLabel],
  );

  return (
    <StationFeedbackContext.Provider value={contextValue}>
      {children}
      {modal === "report" ? (
        <FeedbackModal
          title="上报错误"
          description={`反馈 ${stationLabel} 的分组倍率、充值档位、公告或排名指标错误。`}
          icon={<AlertTriangle size={16} />}
          onClose={closeModal}
        >
          <ReportModalContent onClose={closeModal} />
        </FeedbackModal>
      ) : null}
      {modal === "review" ? (
        <FeedbackModal
          title={reviewPage.viewerReview ? "修改评分" : "我要评分"}
          description={`给 ${stationLabel} 选择 1-5 星（10 分制）并留下公开留言，后续可以回来修改。`}
          icon={<Star size={16} />}
          onClose={closeModal}
        >
          <ReviewModalContent onClose={closeModal} />
        </FeedbackModal>
      ) : null}
    </StationFeedbackContext.Provider>
  );
}

export function StationFeedbackActions() {
  const { reviewPage, openReportModal, openReviewModal } = useStationFeedback();
  const reportButtonRef = useRef<HTMLButtonElement | null>(null);
  const reviewButtonRef = useRef<HTMLButtonElement | null>(null);
  const reviewLabel = reviewPage.viewerReview ? "修改评分" : "我要评分";

  return (
    <div className="hero-feedback-actions" aria-label="站点反馈入口">
      <button
        ref={reportButtonRef}
        type="button"
        className="tiny-button feedback-action-button feedback-action-report"
        onClick={() => openReportModal(reportButtonRef.current)}
      >
        <AlertTriangle size={15} />
        上报错误
      </button>
      <button
        ref={reviewButtonRef}
        type="button"
        className="tiny-button feedback-action-button feedback-action-review"
        onClick={() => openReviewModal(reviewButtonRef.current)}
      >
        <Star size={15} />
        {reviewLabel}
      </button>
    </div>
  );
}

export function StationReviewSection() {
  const { reviewPage, openReviewModal, refreshFirstPage, loadMoreReviews, reviewsLoading } = useStationFeedback();
  const reviewButtonRef = useRef<HTMLButtonElement | null>(null);
  const reviewLabel = reviewPage.viewerReview ? "修改评价" : "写评价";
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState("");

  async function onRefresh() {
    setRefreshing(true);
    setLoadError("");
    try {
      await refreshFirstPage();
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "评价刷新失败。");
    } finally {
      setRefreshing(false);
    }
  }

  async function onLoadMore() {
    setLoadError("");
    try {
      await loadMoreReviews();
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "评价加载失败。");
    }
  }

  return (
    <section id="reviews" className="section feedback-review-section">
      <div className="section-head">
        <div>
          <h2 className="section-title">用户评价</h2>
          <p className="section-desc">展示 GitHub 用户对该站点的公开评分与留言。</p>
        </div>
        <div className="section-head-actions feedback-review-actions">
          <button type="button" className="tiny-button" onClick={onRefresh} disabled={refreshing}>
            {refreshing ? <LoadingIcon size={14} /> : <RefreshCw size={14} />}
            {refreshing ? "刷新中" : "刷新"}
          </button>
          <button
            ref={reviewButtonRef}
            type="button"
            className="tiny-button feedback-submit-button"
            onClick={() => openReviewModal(reviewButtonRef.current)}
          >
            <MessageSquareText size={14} />
            {reviewLabel}
          </button>
        </div>
      </div>
      <div className="section-body">
        <SummaryLine summary={reviewPage.summary} />
        {reviewPage.reviews.length ? (
          <div className="feedback-review-list">
            {reviewPage.reviews.map((review) => (
              <article className="feedback-review-item" key={review.id}>
                <div className="feedback-review-author">
                  {review.githubAvatarUrl ? <img src={review.githubAvatarUrl} alt="" className="feedback-avatar" /> : null}
                  <div>
                    <p>{review.githubLogin}</p>
                    <span>{formatReviewDate(review.updatedAt)} 更新</span>
                  </div>
                </div>
                <div className="feedback-review-score">
                  <RatingStars value={review.rating} />
                  <span>{review.rating} 分 · {ratingLabel(review.rating)}</span>
                </div>
                <p className="feedback-review-comment">{review.comment || "只留下了评分。"}</p>
              </article>
            ))}
          </div>
        ) : (
          <p className="feedback-empty-state">暂无公开评价。</p>
        )}
        {loadError ? <p className={statusClassName("error")}>{loadError}</p> : null}
        {reviewPage.pagination.hasMore ? (
          <div className="feedback-load-more">
            <button type="button" className="tiny-button" onClick={onLoadMore} disabled={reviewsLoading}>
              {reviewsLoading ? <LoadingIcon size={14} /> : null}
              {reviewsLoading ? "加载中" : "加载更多"}
            </button>
          </div>
        ) : null}
      </div>
    </section>
  );
}
