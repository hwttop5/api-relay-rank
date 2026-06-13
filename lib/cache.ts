/**
 * 内存缓存层 - LRU 缓存实现
 * 用于缓存热点数据，减少数据库查询
 */

interface CacheEntry<T> {
  value: T;
  expiry: number;
}

class LRUCache<T> {
  private cache: Map<string, CacheEntry<T>>;
  private readonly maxSize: number;
  private readonly defaultTTL: number;

  constructor(maxSize = 100, defaultTTL = 5 * 60 * 1000) {
    this.cache = new Map();
    this.maxSize = maxSize;
    this.defaultTTL = defaultTTL;
  }

  get(key: string): T | null {
    const entry = this.cache.get(key);
    if (!entry) return null;

    // 检查是否过期
    if (Date.now() > entry.expiry) {
      this.cache.delete(key);
      return null;
    }

    // LRU: 重新插入到末尾
    this.cache.delete(key);
    this.cache.set(key, entry);
    return entry.value;
  }

  set(key: string, value: T, ttl?: number): void {
    // 删除旧值
    this.cache.delete(key);

    // 如果超过容量，删除最旧的项（第一项）
    if (this.cache.size >= this.maxSize) {
      const firstKey = this.cache.keys().next().value;
      if (firstKey !== undefined) {
        this.cache.delete(firstKey);
      }
    }

    // 添加新值
    this.cache.set(key, {
      value,
      expiry: Date.now() + (ttl ?? this.defaultTTL),
    });
  }

  delete(key: string): void {
    this.cache.delete(key);
  }

  clear(): void {
    this.cache.clear();
  }

  size(): number {
    return this.cache.size;
  }
}

// 全局缓存实例
export const rankingCache = new LRUCache<unknown>(100, 5 * 60 * 1000);
export const stationCache = new LRUCache<unknown>(200, 10 * 60 * 1000);
export const statsCache = new LRUCache<unknown>(50, 5 * 60 * 1000);
