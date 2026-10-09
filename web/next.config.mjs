/** @type {import('next').NextConfig} */
const nextConfig = {
  transpilePackages: ["@fm/shared"],
  async rewrites() {
    return [];
  },
};
export default nextConfig;
