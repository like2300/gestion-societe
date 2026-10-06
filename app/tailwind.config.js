/** @type {import('tailwindcss').Config} */
module.exports = {
    content: ["./templates/**/*.html"],
    theme: {
        extend: {
            colors: {
                brand: {
                    background: "#ffffff", // fond de page : blanc
                    title: "#2563eb", // titres : bleu
                    text: "#000000", // texte : noir
                    border: "#0ea5e9", // bordures : bleu ciel
                    primary: "#0284c7", // boutons : bleu ciel
                    "primary-hover": "#0369a1",
                },
            },
        },
    },
    plugins: [],
};