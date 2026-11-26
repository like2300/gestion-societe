"use client";

import { TestimonialGlobe } from "@/components/ui/testimonial-globe";
import type { GlobeTestimonial } from "@/components/ui/testimonial-globe";

// Témoignages clients adaptés au garage "Garage du Quartier".
// Photos Unsplash (portraits sous licence Unsplash).
export const GARAGE_TESTIMONIALS: GlobeTestimonial[] = [
  {
    id: "paris",
    quote: "Service rapide et honnête. Ils m'ont expliqué exactement ce qu'il fallait changer sur ma voiture. Le prix a été tenu.",
    name: "Marie Durand",
    role: " Conductrice",
    company: "Paris 11e",
    city: "Paris",
    country: "FR",
    lat: 48.86,
    lng: 2.35,
    image: "https://images.unsplash.com/photo-1438761681033-6461ffad8d80?q=80&w=200&h=200&auto=format&fit=crop",
    rating: 5,
    tone: 1,
  },
  {
    id: "lyon",
    quote: "Révision faite en moins d'une heure, avec un devis clair avant. Je recommande les yeux fermés.",
    name: "Karim Salah",
    role: "Commerçant",
    company: "Lyon 3e",
    city: "Lyon",
    country: "FR",
    lat: 45.76,
    lng: 4.84,
    image: "https://images.unsplash.com/photo-1507003211169-0a1272a8e396?q=80&w=200&h=200&auto=format&fit=crop",
    rating: 5,
    tone: 2,
  },
  {
    id: "marseille",
    quote: "Je viens depuis 3 ans. Jamais de mauvaise surprise. Le garage de confiance du quartier.",
    name: "Sophie Laurent",
    role: "Professeure",
    company: "Marseille",
    city: "Marseille",
    country: "FR",
    lat: 43.30,
    lng: 5.37,
    image: "https://images.unsplash.com/photo-1527980965255-d3b416303d12?q=80&w=200&h=200&auto=format&fit=crop",
    rating: 5,
    tone: 3,
  },
  {
    id: "bordeaux",
    quote: "Climatisation rechargée en 30 minutes. Accueil sympathique, voiture rendue propre.",
    name: "Thomas Moreau",
    role: "Ingénieur",
    company: "Bordeaux",
    city: "Bordeaux",
    country: "FR",
    lat: 44.84,
    lng: -0.58,
    image: "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?q=80&w=200&h=200&auto=format&fit=crop",
    rating: 4,
    tone: 4,
  },
  {
    id: "nantes",
    quote: "Pneus changés le jour même. Devis gratuit, pas de surprise sur la facture finale.",
    name: "Élise Dubois",
    role: "Infirmière",
    company: "Nantes",
    city: "Nantes",
    country: "FR",
    lat: 47.22,
    lng: -1.55,
    image: "https://images.unsplash.com/photo-1524504388940-b1c1722653e1?q=80&w=200&h=200&auto=format&fit=crop",
    rating: 5,
    tone: 5,
  },
  {
    id: "strasbourg",
    quote: "Freins refaits impeccablement. Je repars en confiance pour les vacances.",
    name: "Lucas Petit",
    role: "Étudiant",
    company: "Strasbourg",
    city: "Strasbourg",
    country: "FR",
    lat: 48.58,
    lng: 7.75,
    image: "https://images.unsplash.com/photo-1506863528982-f4a858b40fdd?q=80&w=200&h=200&auto=format&fit=crop",
    rating: 5,
    tone: 1,
  },
  {
    id: "lille",
    quote: "Diagnostic électronique rapide. Ils ont trouvé le défaut que le concessionnaire avait manqué.",
    name: "Camille Rouault",
    role: "Graphiste",
    company: "Lille",
    city: "Lille",
    country: "FR",
    lat: 50.63,
    lng: 3.06,
    image: "https://images.unsplash.com/photo-1494790108377-be9c29b29330?q=80&w=200&h=200&auto=format&fit=crop",
    rating: 4,
    tone: 2,
  },
  {
    id: "toulouse",
    quote: "Carrosserie après un accrochage. La peinture est identique à l'origine. Très professionnel.",
    name: "Hugo Bernard",
    role: "Cadre",
    company: "Toulouse",
    city: "Toulouse",
    country: "FR",
    lat: 43.60,
    lng: 1.44,
    image: "https://images.unsplash.com/photo-1534528741775-53994a69daeb?q=80&w=200&h=200&auto=format&fit=crop",
    rating: 5,
    tone: 3,
  },
];

export default function GarageTestimonials() {
  return (
    <section id="temoignages" className="py-20 border-y border-border">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <TestimonialGlobe
          items={GARAGE_TESTIMONIALS}
          eyebrow="Ce qu'ils disent du garage"
          heading="Des clients du quartier, satisfaits."
          caption="Témoignages réels de conducteurs accompagnés par Garage du Quartier."
          autoRotate={true}
          autoplay={true}
          interval={4000}
          size={420}
          action={
            <a
              href="#rendez-vous"
              className="inline-flex h-9 items-center gap-1.5 rounded-full bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              Prendre rendez-vous
            </a>
          }
        />
      </div>
    </section>
  );
}
