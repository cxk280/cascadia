/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // `standalone` output emits a self-contained .next/standalone/ tree with a
  // pruned node_modules, so the production Docker image stays small and the
  // runtime stage doesn't need npm or the full devDeps closure.
  output: "standalone",
};

export default nextConfig;
