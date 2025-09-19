/**
 * Tailwind CSS configuration used to build the precompiled stylesheet committed to the repository.
 *
 * Developers can regenerate `backend/static/css/tailwind.min.css` by running:
 *   NODE_ENV=production npx tailwindcss -i backend/static/css/tailwind.src.css -o backend/static/css/tailwind.min.css --minify
 * when Node.js is available, or by downloading the standalone CLI binary for Tailwind.
 */
module.exports = {
  content: [
    "./backend/templates/**/*.html",
    "./backend/**/*.py",
  ],
  theme: {
    extend: {
      container: {
        center: true,
        padding: "1rem",
      },
    },
  },
  plugins: [],
};
