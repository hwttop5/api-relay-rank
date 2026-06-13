/**
 * API 响应压缩中间件
 * 自动压缩 JSON 响应以减少传输体积
 */

import { NextResponse } from 'next/server';

export function compressedJson(
  data: unknown,
  init?: ResponseInit
): NextResponse {
  const response = NextResponse.json(data, init);
  
  // Next.js 会在生产环境自动启用 gzip/brotli
  // 这里只需要确保响应头正确设置
  response.headers.set('Content-Type', 'application/json; charset=utf-8');
  
  // 添加缓存控制头
  if (!response.headers.has('Cache-Control')) {
    response.headers.set('Cache-Control', 'public, max-age=300, stale-while-revalidate=600');
  }
  
  return response;
}

/**
 * 为静态 API 响应添加长期缓存
 */
export function cachedJson(
  data: unknown,
  maxAge: number = 3600
): NextResponse {
  const response = NextResponse.json(data);
  response.headers.set('Content-Type', 'application/json; charset=utf-8');
  response.headers.set('Cache-Control', `public, max-age=${maxAge}, stale-while-revalidate=${maxAge * 2}`);
  return response;
}
