/** @type {import('next').NextConfig} */
const nextConfig = {
  distDir: process.env.NODE_ENV === "development" ? ".next-dev" : ".next",
  typedRoutes: true,
  allowedDevOrigins: ["127.0.0.1", "localhost", "192.168.5.2"]
};

export default nextConfig;
