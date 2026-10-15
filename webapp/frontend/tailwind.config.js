/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef6ff",
          100: "#d9ebff",
          500: "#2b7fff",
          600: "#1a6bf0",
          700: "#1657c4",
        },
      },
    },
  },
  plugins: [],
};
