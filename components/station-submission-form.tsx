"use client";

import { useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { signIn, signOut } from "next-auth/react";
import {
  AlertTriangle,
  CheckCircle2,
  FileImage,
  Github,
  KeyRound,
  Link as LinkIcon,
  Loader2,
  LogOut,
  Mail,
  Send,
  Upload,
  X,
} from "lucide-react";

import {
  STATION_SUBMISSION_PAYMENT_TYPES,
  STATION_SUBMISSION_PLATFORMS,
} from "@/lib/station-submissions";
import type { AuthenticatedGithubUser, StationSubmissionPaymentType, StationSubmissionPlatform } from "@/lib/types";
import { SelectControl } from "@/components/ui/select-control";

interface StationSubmissionFormProps {
  viewer: AuthenticatedGithubUser | null;
  authConfigured: boolean;
  databaseConfigured: boolean;
  reviewNotes: readonly string[];
  testNotes: readonly string[];
}

type StatusState = { tone: "success" | "error" | "info"; message: string; submissionId?: number } | null;

const initialPaymentType: StationSubmissionPaymentType = "non_subscription";
const initialPlatform: StationSubmissionPlatform = "new_api";
const MAX_SCREENSHOTS_PER_FIELD = 3;
const SCREENSHOT_LIMIT_MESSAGE = "最多只能上传3张图";

function statusClassName(tone: "success" | "error" | "info") {
  if (tone === "success") {
    return "feedback-status feedback-status-success";
  }
  if (tone === "error") {
    return "feedback-status feedback-status-error";
  }
  return "feedback-status";
}

function LoadingIcon({ size = 15 }: { size?: number }) {
  return <Loader2 size={size} className="spin-icon" aria-hidden="true" />;
}

function formatFileSize(bytes: number) {
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

async function readResponsePayload(response: Response): Promise<Record<string, unknown> | null> {
  const text = await response.text();
  if (!text.trim()) {
    return null;
  }
  try {
    const payload = JSON.parse(text);
    return payload && typeof payload === "object" && !Array.isArray(payload) ? (payload as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function responseFallbackMessage(response: Response) {
  if (response.status === 401) {
    return "请先登录 GitHub 后再提交。";
  }
  if (response.status === 413) {
    return "上传内容过大，请压缩截图后再提交。";
  }
  if (response.status >= 500) {
    return "服务器暂时无法保存申请，请稍后再试。";
  }
  return response.statusText ? `提交失败（HTTP ${response.status} ${response.statusText}）。` : `提交失败（HTTP ${response.status}）。`;
}

function UploadedFileRow({
  label,
  files,
  disabled,
  onClear,
}: {
  label: string;
  files: File[];
  disabled: boolean;
  onClear: (index: number) => void;
}) {
  if (!files.length) {
    return null;
  }

  return (
    <div className="submission-file-list" aria-live="polite">
      {files.map((file, index) => (
        <div className="submission-file-item" key={`${file.name}-${file.size}-${file.lastModified}-${index}`}>
          <FileImage size={15} aria-hidden="true" />
          <span className="submission-file-name" title={file.name}>
            {file.name}
          </span>
          <span className="submission-file-size">{formatFileSize(file.size)}</span>
          <button type="button" className="submission-file-remove-button" onClick={() => onClear(index)} disabled={disabled} aria-label={`移除${label}${index + 1}`}>
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      ))}
    </div>
  );
}

function appendScreenshotFiles(currentFiles: File[], selectedFiles: File[]) {
  return [...currentFiles, ...selectedFiles].slice(0, MAX_SCREENSHOTS_PER_FIELD);
}

function SubmissionNotes({ reviewNotes, testNotes }: { reviewNotes: readonly string[]; testNotes: readonly string[] }) {
  return (
    <aside className="submission-notes" aria-label="申请说明">
      <div className="notice-panel notice-panel-primary">
        <h2 className="submission-side-title">收录说明</h2>
        <div className="bullet-list">
          {reviewNotes.map((item) => (
            <div className="bullet-item" key={item}>
              <span className="bullet-prefix">•</span>
              <p className="bullet-copy">{item}</p>
            </div>
          ))}
        </div>
      </div>
      <div className="notice-panel">
        <h2 className="submission-side-title">测试说明</h2>
        <div className="bullet-list">
          {testNotes.map((item) => (
            <div className="bullet-item" key={item}>
              <span className="bullet-prefix">•</span>
              <p className="bullet-copy">{item}</p>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}

export function StationSubmissionForm({ viewer, authConfigured, databaseConfigured, reviewNotes, testNotes }: StationSubmissionFormProps) {
  const [stationName, setStationName] = useState("");
  const [officialUrl, setOfficialUrl] = useState("");
  const [paymentType, setPaymentType] = useState<StationSubmissionPaymentType>(initialPaymentType);
  const [platform, setPlatform] = useState<StationSubmissionPlatform>(initialPlatform);
  const [platformNote, setPlatformNote] = useState("");
  const [groupMultiplier, setGroupMultiplier] = useState("");
  const [rechargeMultiplier, setRechargeMultiplier] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [testBaseUrl, setTestBaseUrl] = useState("");
  const [testApiKey, setTestApiKey] = useState("");
  const [notes, setNotes] = useState("");
  const [groupScreenshots, setGroupScreenshots] = useState<File[]>([]);
  const [rechargeScreenshots, setRechargeScreenshots] = useState<File[]>([]);
  const [screenshotWarning, setScreenshotWarning] = useState<string | null>(null);
  const [status, setStatus] = useState<StatusState>(null);
  const [submitting, setSubmitting] = useState(false);
  const groupFileInputRef = useRef<HTMLInputElement | null>(null);
  const rechargeFileInputRef = useRef<HTMLInputElement | null>(null);

  function clearScreenshotLimitStatus() {
    setScreenshotWarning(null);
    setStatus((currentStatus) => (currentStatus?.message === SCREENSHOT_LIMIT_MESSAGE ? null : currentStatus));
  }

  function handleScreenshotSelection(kind: "group" | "recharge", files: FileList | null) {
    const selectedFiles = Array.from(files || []);
    if (!selectedFiles.length) {
      return;
    }
    const setFiles = kind === "group" ? setGroupScreenshots : setRechargeScreenshots;
    setFiles((currentFiles) => {
      const nextFiles = appendScreenshotFiles(currentFiles, selectedFiles);
      if (currentFiles.length + selectedFiles.length > MAX_SCREENSHOTS_PER_FIELD) {
        setScreenshotWarning(SCREENSHOT_LIMIT_MESSAGE);
        setStatus({ tone: "error", message: SCREENSHOT_LIMIT_MESSAGE });
      } else {
        clearScreenshotLimitStatus();
      }
      return nextFiles;
    });
  }

  function clearGroupScreenshot(index: number) {
    setGroupScreenshots((files) => files.filter((_, fileIndex) => fileIndex !== index));
    clearScreenshotLimitStatus();
    if (groupFileInputRef.current) {
      groupFileInputRef.current.value = "";
    }
  }

  function clearRechargeScreenshot(index: number) {
    setRechargeScreenshots((files) => files.filter((_, fileIndex) => fileIndex !== index));
    clearScreenshotLimitStatus();
    if (rechargeFileInputRef.current) {
      rechargeFileInputRef.current.value = "";
    }
  }

  function resetForm() {
    setStationName("");
    setOfficialUrl("");
    setPaymentType(initialPaymentType);
    setPlatform(initialPlatform);
    setPlatformNote("");
    setGroupMultiplier("");
    setRechargeMultiplier("");
    setContactEmail("");
    setTestBaseUrl("");
    setTestApiKey("");
    setNotes("");
    setGroupScreenshots([]);
    setRechargeScreenshots([]);
    setScreenshotWarning(null);
    setStatus(null);
    if (groupFileInputRef.current) {
      groupFileInputRef.current.value = "";
    }
    if (rechargeFileInputRef.current) {
      rechargeFileInputRef.current.value = "";
    }
  }

  async function submitForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!viewer || submitting) {
      return;
    }
    if (!groupScreenshots.length || !rechargeScreenshots.length) {
      setStatus({ tone: "error", message: "请上传分组倍率和充值倍率截图。" });
      return;
    }
    setScreenshotWarning(null);
    setSubmitting(true);
    setStatus({ tone: "info", message: "正在提交申请..." });
    try {
      const formData = new FormData();
      formData.set("stationName", stationName);
      formData.set("officialUrl", officialUrl);
      formData.set("paymentType", paymentType);
      formData.set("platform", platform);
      formData.set("platformNote", platformNote);
      formData.set("groupMultiplier", groupMultiplier);
      formData.set("rechargeMultiplier", rechargeMultiplier);
      formData.set("contactEmail", contactEmail);
      formData.set("testBaseUrl", testBaseUrl);
      formData.set("testApiKey", testApiKey);
      formData.set("notes", notes);
      formData.set("currentUrl", window.location.href);
      for (const file of groupScreenshots) {
        formData.append("groupScreenshot", file);
      }
      for (const file of rechargeScreenshots) {
        formData.append("rechargeScreenshot", file);
      }
      const response = await fetch("/api/station-submissions", {
        method: "POST",
        headers: { accept: "application/json" },
        body: formData,
      });
      const payload = await readResponsePayload(response);
      if (!response.ok) {
        const payloadError = typeof payload?.error === "string" && payload.error.trim() ? payload.error : null;
        throw new Error(payloadError || responseFallbackMessage(response));
      }
      setTestApiKey("");
      setStatus({
        tone: "success",
        message: "感谢您的提交，我们已收到申请。我们会尽快汇总资料、完成审核，并开始测试与数据采集；预计最迟一周后完成入榜评估，请耐心等待。感谢您的支持。",
        submissionId: typeof payload?.submissionId === "number" ? payload.submissionId : undefined,
      });
    } catch (error) {
      setStatus({ tone: "error", message: error instanceof Error ? error.message : "申请提交失败。" });
    } finally {
      setSubmitting(false);
    }
  }

  if (!databaseConfigured) {
    return (
      <>
        <SubmissionNotes reviewNotes={reviewNotes} testNotes={testNotes} />
        <div className="submission-state-panel">
          <AlertTriangle size={22} />
          <div>
            <h3>暂时无法提交</h3>
            <p>当前实例未配置 PostgreSQL，申请资料无法安全保存。请稍后再试。</p>
          </div>
        </div>
      </>
    );
  }

  if (!authConfigured) {
    return (
      <>
        <SubmissionNotes reviewNotes={reviewNotes} testNotes={testNotes} />
        <div className="submission-state-panel">
          <AlertTriangle size={22} />
          <div>
            <h3>GitHub 登录未配置</h3>
            <p>申请收录需要 GitHub 登录；当前实例缺少 OAuth 配置，表单暂不可用。</p>
          </div>
        </div>
      </>
    );
  }

  if (!viewer) {
    return (
      <>
        <SubmissionNotes reviewNotes={reviewNotes} testNotes={testNotes} />
        <div className="submission-login-panel">
          <div>
            <h3>登录后提交申请</h3>
            <p>申请会记录 GitHub 账号、联系邮箱和站点资料，用于减少垃圾提交并方便后续核验。</p>
          </div>
          <button type="button" className="tiny-button feedback-login-button" onClick={() => signIn("github", { callbackUrl: window.location.href })}>
            <Github size={15} />
            使用 GitHub 登录
          </button>
        </div>
      </>
    );
  }

  if (status?.tone === "success") {
    return (
      <div className="submission-success-panel">
        <CheckCircle2 size={24} />
        <div className="submission-success-content">
          <h3>申请已收到</h3>
          <p>
            {status.message}
            {status.submissionId ? ` 申请编号：#${status.submissionId}` : ""}
          </p>
          <div className="feedback-modal-actions submission-success-actions">
            <button type="button" className="tiny-button feedback-secondary-button" onClick={resetForm}>
              继续提交
            </button>
            <Link href="/" className="tiny-button feedback-secondary-button">
              回到首页
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      <SubmissionNotes reviewNotes={reviewNotes} testNotes={testNotes} />

      <div className="submission-userbar">
        <div className="feedback-user">
          {viewer.avatarUrl ? <img src={viewer.avatarUrl} alt="" className="feedback-avatar" /> : null}
          <div>
            <p>{viewer.githubLogin}</p>
            <span>已登录 GitHub，申请会记录该账号。</span>
          </div>
        </div>
        <button type="button" className="tiny-button feedback-login-button" onClick={() => signOut({ callbackUrl: window.location.href })}>
          <LogOut size={14} />
          退出登录
        </button>
      </div>

      <form className="submission-form" onSubmit={submitForm}>
        <div className="submission-form-grid">
          <label className="feedback-field">
            <span>站点名称</span>
            <input value={stationName} onChange={(event) => setStationName(event.target.value)} maxLength={120} required disabled={submitting} placeholder="例如：OpenAI" />
          </label>
          <label className="feedback-field">
            <span>官网地址</span>
            <div className="submission-input-with-icon">
              <LinkIcon size={15} />
              <input value={officialUrl} onChange={(event) => setOfficialUrl(event.target.value)} inputMode="url" required disabled={submitting} placeholder="https://example.com" />
            </div>
          </label>
          <label className="feedback-field">
            <span>付费类型</span>
            <SelectControl
              ariaLabel="付费类型"
              name="paymentType"
              value={paymentType}
              disabled={submitting}
              options={STATION_SUBMISSION_PAYMENT_TYPES.map((item) => ({ value: item.value, label: item.label }))}
              onChange={setPaymentType}
            />
          </label>
          <label className="feedback-field">
            <span>平台判断</span>
            <SelectControl
              ariaLabel="平台判断"
              name="platform"
              value={platform}
              disabled={submitting}
              options={STATION_SUBMISSION_PLATFORMS}
              onChange={setPlatform}
            />
          </label>
        </div>

        {platform === "other" ? (
          <label className="feedback-field">
            <span>平台说明</span>
            <input value={platformNote} onChange={(event) => setPlatformNote(event.target.value)} maxLength={300} required disabled={submitting} placeholder="请说明后台系统或自研情况" />
          </label>
        ) : null}

        <div className="submission-form-grid submission-screenshot-grid">
          <div className="feedback-field submission-screenshot-copy">
            <span>分组倍率说明</span>
            <textarea value={groupMultiplier} onChange={(event) => setGroupMultiplier(event.target.value)} maxLength={1000} rows={5} required disabled={submitting} placeholder="请写明最低倍率分组、Codex/Claude Code 可用分组，以及截图对应位置。" />
          </div>
          <div className="feedback-field submission-screenshot-copy">
            <span>充值倍率说明</span>
            <textarea value={rechargeMultiplier} onChange={(event) => setRechargeMultiplier(event.target.value)} maxLength={1000} rows={5} required disabled={submitting} placeholder="例如：1:1，即 1 人民币兑换 1 美金额度；请说明截图中的充值档位。" />
          </div>
          <div className="submission-upload-control">
            <label className="feedback-file-button submission-file-button">
              <Upload size={15} />
              <span>上传分组倍率截图</span>
              <input
                ref={groupFileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                multiple
                disabled={submitting}
                onChange={(event) => {
                  handleScreenshotSelection("group", event.currentTarget.files);
                  event.currentTarget.value = "";
                }}
              />
            </label>
            <small>最多 {MAX_SCREENSHOTS_PER_FIELD} 张，单张 5MB，支持 PNG/JPEG/WebP。</small>
          </div>
          <div className="submission-upload-control">
            <label className="feedback-file-button submission-file-button">
              <Upload size={15} />
              <span>上传充值倍率截图</span>
              <input
                ref={rechargeFileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                multiple
                disabled={submitting}
                onChange={(event) => {
                  handleScreenshotSelection("recharge", event.currentTarget.files);
                  event.currentTarget.value = "";
                }}
              />
            </label>
            <small>最多 {MAX_SCREENSHOTS_PER_FIELD} 张，单张 5MB，支持 PNG/JPEG/WebP。</small>
          </div>
          {screenshotWarning ? (
            <p className="feedback-status feedback-status-error submission-screenshot-warning" role="alert">
              <AlertTriangle size={14} />
              {screenshotWarning}
            </p>
          ) : null}
          <div className="submission-screenshot-list-slot">
            <UploadedFileRow label="分组倍率截图" files={groupScreenshots} disabled={submitting} onClear={clearGroupScreenshot} />
          </div>
          <div className="submission-screenshot-list-slot">
            <UploadedFileRow label="充值倍率截图" files={rechargeScreenshots} disabled={submitting} onClear={clearRechargeScreenshot} />
          </div>
        </div>

        <div className="submission-form-grid submission-credential-grid">
          <label className="feedback-field">
            <span>测试 BaseURL</span>
            <div className="submission-input-with-icon">
              <LinkIcon size={15} />
              <input value={testBaseUrl} onChange={(event) => setTestBaseUrl(event.target.value)} inputMode="url" required disabled={submitting} placeholder="https://api.example.com" />
            </div>
          </label>
          <label className="feedback-field">
            <span>测试 API Key</span>
            <div className="submission-input-with-icon">
              <KeyRound size={15} />
              <input value={testApiKey} onChange={(event) => setTestApiKey(event.target.value)} type="password" minLength={8} maxLength={500} required disabled={submitting} placeholder="请确保有测试额度且为 Codex 最低倍率分组" autoComplete="off" />
            </div>
          </label>
        </div>

        <label className="feedback-field">
          <span>联系邮箱</span>
          <div className="submission-input-with-icon">
            <Mail size={15} />
            <input value={contactEmail} onChange={(event) => setContactEmail(event.target.value)} inputMode="email" type="email" maxLength={254} required disabled={submitting} placeholder="owner@example.com" />
          </div>
        </label>

        <label className="feedback-field">
          <span>补充说明</span>
          <textarea value={notes} onChange={(event) => setNotes(event.target.value)} maxLength={1500} rows={4} disabled={submitting} placeholder="可以补充模型分组、公益规则、站点限制、希望优先测试的模型等。" />
        </label>

        {status ? (
          <p className={statusClassName(status.tone)}>
            {status.tone === "info" ? <LoadingIcon size={14} /> : status.tone === "error" ? <AlertTriangle size={14} /> : null}
            {status.message}
          </p>
        ) : null}

        <div className="submission-actions">
          <button type="button" className="tiny-button feedback-secondary-button" onClick={resetForm} disabled={submitting}>
            清空
          </button>
          <button type="submit" className="tiny-button feedback-submit-button" disabled={submitting}>
            {submitting ? <LoadingIcon /> : <Send size={15} />}
            {submitting ? "正在提交" : "提交申请"}
          </button>
        </div>
      </form>
    </>
  );
}
