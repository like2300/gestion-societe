# Integration du composant TestimonialGlobe

## Etat actuel du projet

Le projet est une application Django avec une page d'atterrissage HTML statique.
- Il n'y a pas de React.
- Il n'y a pas de TypeScript.
- Il n'y a pas de shadcn/ui.
- Il n'y a pas de Node.js ni de npm.
- Tailwind CSS est charge via CDN sur `landing/index.html`.

Pour utiliser le composant `TestimonialGlobe`, vous devez ajouter une pile
frontend React + shadcn/ui + Tailwind + TypeScript.

## Pourquoi le dossier /components/ui est important

shadcn/ui attend ses composants dans `/components/ui`. Ce dossier est la
convention par défaut de shadcn. Les fichiers de configuration (tailwind,
tsconfig, vite) y font reference. Sans ce dossier, les imports du type
`@/components/ui/testimonial-globe` ne fonctionnent pas.

## Etape 0 - Installer Node.js et npm

1. Telechargez Node.js (LTS) sur https://nodejs.org/.
2. Installez-le.
3. Verifiez l'installation :
   ```bash
   node --version
   npm --version
   ```

## Etape 1 - Initialiser le projet frontend

Dans la racine du projet (`/home/omerlinks/clients/gestion societe`) :

```bash
npm init -y
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
npm install react react-dom
npm install -D @vitejs/plugin-react vite typescript @types/react @types/react-dom
```

## Etape 2 - Installer shadcn/ui

```bash
npx shadcn@latest init
```

Repondez aux questions :
- Style : default (ou votre choix)
- Couleur : slate (ou votre choix)
- Fichier CSS : globals.css (chemin propose)
- Votre fichier globals.css existe deja : `components/ui/globals.css`

Apres l'init, shadcn cree :
- `components.json`
- `tailwind.config.ts` (ou met a jour `tailwind.config.js`)
- `tsconfig.json`
- `vite.config.ts`
- `index.html` (ou utilise votre fichier existant)

## Etape 3 - Installer la dependance cobe

Le composant utilise la librairie `cobe` pour le globe WebGL.

```bash
npm install cobe
```

## Etape 4 - Installer lucide-react (icones)

Le composant contient ses propres SVG en ligne. Pour remplacer ces SVG par
des icones lucide-react (recommande pour la coherence) :

```bash
npm install lucide-react
```

Puis remplacez `Chevron`, `StarIcon` et `QuoteMark` dans
`components/ui/testimonial-globe.tsx` par les composants Lucide equivalents.

## Etape 5 - Copier les fichiers du composant

Les fichiers sont deja places :

- `components/ui/testimonial-globe.tsx` — le composant principal
- `components/ui/testimonial-globe-demo.tsx` — exemple d'utilisation
- `components/ui/globals.css` — variables CSS shadcn (fond, texte, chart-1…5)

## Etape 6 - Configurer les chemins d'import

Dans `tsconfig.json`, ajoutez ou verifiez le alias :

```json
{
  "compilerOptions": {
    "paths": {
      "@/*": ["./*"]
    }
  }
}
```

L'import `@/components/ui/testimonial-globe` resolvra alors vers
`components/ui/testimonial-globe.tsx`.

## Etape 7 - Monter le composant sur la page d'atterrissage

La section `#temoignages` de `landing/index.html` contient maintenant un
conteneur :

```html
<div id="testimonial-globe-root" class="reveal min-h-[560px] flex items-center justify-center">
  <p class="text-garage-muted text-sm">Chargement des témoignages…</p>
</div>
```

Pour monter le composant React :

1. Creez un point d'entree `main.tsx` qui rend `GarageTestimonials` dans
   `#testimonial-globe-root`.
2. Build avec Vite :
   ```bash
   npx vite build
   ```
3. Chargez le bundle JS genere dans `landing/index.html` (balise
   `<script type="module" src="..."></script>` avant `</body>`).

## Etape 8 - Remplir les images

Les images du demo utilisent Unsplash (licence gratuite). Pour la production,
remplacez-les par des photos reelles de vos clients (portraits carrés).

## Structure finale attendue

```
/home/omerlinks/clients/gestion societe/
├── components/
│   └── ui/
│       ├── testimonial-globe.tsx
│       ├── testimonial-globe-demo.tsx
│       └── globals.css
├── landing/
│   └── index.html
├── app/ (Django backend)
├── package.json
├── tailwind.config.js
├── tsconfig.json
├── vite.config.ts
└── index.html (entrée Vite, optionnel)
```

## Donnees passees au composant

Le composant recoit `items` (tableau de `GlobeTestimonial`). Chaque item
contient :
- `id` : identifiant unique
- `quote` : texte du temoignage (1-2 phrases)
- `name` : nom du client
- `role` : fonction (optionnel)
- `company` : entreprise (optionnel)
- `city` : ville (affiche sur la carte et la carte)
- `country` : code pays ISO-2 (optionnel)
- `lat`, `lng` : coordonnées GPS pour la position sur le globe
- `image` : URL du portrait carré
- `rating` : note 1-5 (optionnel)
- `tone` : couleur de l'anneau (1-5, optionnel)

Le composant gere lui-meme :
- La rotation automatique du globe
- L'accessibilite (clavier, lecteurs d'ecran)
- Le mode reduit de mouvement
- L'adaptation a la taille de l'ecran
- Le basculement entre temoignages avec animation
