import {
  Camera,
  CheckCircle2,
  Compass,
  DollarSign,
  Eye,
  GitCompare,
  Home as HomeIcon,
  Layers,
  Link2,
  Mail,
  Map as MapIcon,
  MapPin,
  Mic,
  Radio,
  Ruler,
  Shield,
  Sparkles,
  Trash2,
  Users,
  Video,
  Zap,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";

export const metadata = {
  title: "HomeAnalyzer · Features",
  description:
    "Tour with confidence. Live notes, AI-generated briefs, and easy comparison across every house you've seen.",
};

type Feature = {
  icon: LucideIcon;
  title: string;
  body: string;
};

type Section = {
  heading: string;
  blurb?: string;
  features: Feature[];
};

const sections: Section[] = [
  {
    heading: "Tour with your family watching live",
    features: [
      {
        icon: Radio,
        title: "A quiet bot joins the Zoom",
        body: "Tap Start Tour. A silent assistant joins your Zoom so anyone you invite can watch the walkthrough.",
      },
      {
        icon: Mic,
        title: "Live transcript",
        body: "Words appear on screen seconds after they're spoken — for you, for whoever's watching.",
      },
      {
        icon: Eye,
        title: "Notes organize themselves",
        body: "Observations populate automatically — hazards, concerns, layout, condition, positives, agent quotes. No clipboard.",
      },
      {
        icon: Mail,
        title: "Invitees auto-emailed at start",
        body: "Everyone you invited gets the Zoom link the moment you tap Start. One tap to join.",
      },
    ],
  },
  {
    heading: "Catch what you'd miss in person",
    features: [
      {
        icon: Video,
        title: "It watches the video too",
        body: "After the tour, the app reviews the recording and flags visual details no one called out — water stains, chipped cabinets, peeling paint.",
      },
      {
        icon: CheckCircle2,
        title: "Audio and visual together",
        body: "If the agent mentioned a leak and the camera caught it, you see one note backed by both — not duplicates.",
      },
      {
        icon: Camera,
        title: "Photo notes on the spot",
        body: "Snap a picture of anything that catches your eye — a stain, a fixture, a question for the agent. The app reads it and adds an observation automatically.",
      },
    ],
  },
  {
    heading: "See the layout, not just the walls",
    blurb:
      "After your tour, the app reconstructs the floor plan from the video — actual dimensions, not estimates.",
    features: [
      {
        icon: Ruler,
        title: "Measured rooms in feet and meters",
        body: "Tap any room to see how big it is. Sizes come from the video itself, so they reflect the home you walked through, not a listing summary.",
      },
      {
        icon: Layers,
        title: "Honest about confidence",
        body: "Rooms the camera covered well are drawn solid; under-covered rooms show as dashed outlines so you know which numbers to trust.",
      },
      {
        icon: Sparkles,
        title: "Generates on its own",
        body: "Nothing to click. The plan is ready a few minutes after you finish — same flow as the brief.",
      },
    ],
  },
  {
    heading: "A clear brief at the end of every tour",
    features: [
      {
        icon: Sparkles,
        title: "Summary, concerns, deal-breakers, score",
        body: "A short, scannable post-tour brief — and a 0–10 score so you can rank at a glance.",
      },
      {
        icon: GitCompare,
        title: "Compare any houses, anytime",
        body: 'Pick a few — even from different tours — and ask in plain English: "Which had the best kitchen for kids?"',
      },
      {
        icon: DollarSign,
        title: "Sale or rent, framed right",
        body: "Mark a property for sale or for rent and the brief adapts — resale strategy or lease considerations.",
      },
    ],
  },
  {
    heading: "Tour solo when Zoom isn't an option",
    features: [
      {
        icon: Mic,
        title: "Record right in the browser",
        body: "Tap one button and speak — your phone does the recording, the app does the rest. No separate app to install.",
      },
      {
        icon: HomeIcon,
        title: "Or upload after the fact",
        body: "Already recorded with another app? Drop the file in. Same brief, same observations, same comparison.",
      },
    ],
  },
  {
    heading: "Adding a house takes ten seconds",
    features: [
      {
        icon: Zap,
        title: "Quick Tour for spontaneous viewings",
        body: "Type an address and you're in the house page. Skips the create-tour-first dance for drive-bys.",
      },
      {
        icon: MapPin,
        title: "Use my location",
        body: "Standing on the porch? One tap fills in the address from your phone.",
      },
      {
        icon: Camera,
        title: "Curb appeal photo",
        body: "Snap an exterior shot in the form. Remember which one had the blue shutters.",
      },
      {
        icon: Compass,
        title: "One-tap listing search",
        body: "Search Zillow, Redfin, or Google with the address — no retyping.",
      },
    ],
  },
  {
    heading: "See everything you've toured at once",
    features: [
      {
        icon: MapIcon,
        title: "Map of every house",
        body: "Pins for every property you've toured, colored by your score. Spot neighborhood patterns at a glance.",
      },
    ],
  },
  {
    heading: "Bring your team along",
    features: [
      {
        icon: Users,
        title: "One-tap email invites",
        body: "Invite your partner, parent, agent, or a friend. They click the email and they're in — no password.",
      },
      {
        icon: Shield,
        title: "Roles that match real life",
        body: "Buyer, partner, agent, friend & family. Everyone sees the same notes and briefs.",
      },
      {
        icon: Link2,
        title: "Share a read-only link",
        body: "Send the tour summary to family, your lender, or a lawyer with one URL. They see the brief and the photos — no login. Revoke anytime.",
      },
    ],
  },
  {
    heading: "Built to keep things tidy",
    features: [
      {
        icon: Trash2,
        title: "Swipe to delete, fully",
        body: "Swipe a tour or house off the list — recordings, observations, photos, all gone.",
      },
      {
        icon: Shield,
        title: "Private by default",
        body: "Your recordings stay in your private storage. Invitees only see what you share with them.",
      },
    ],
  },
];

export default function FeaturesPage() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-zinc-200 dark:border-zinc-800 bg-white/85 dark:bg-zinc-950/85 backdrop-blur sticky top-0 z-10">
        <div className="mx-auto max-w-3xl flex items-center justify-between px-5 py-3">
          <Link href="/" className="flex items-center gap-2 group">
            <span className="inline-flex items-center justify-center size-8 rounded-lg bg-primary text-primary-foreground">
              <HomeIcon className="size-4" strokeWidth={2.5} />
            </span>
            <span
              className="font-bold text-lg tracking-tight leading-none"
              style={{ fontFamily: "var(--font-display)" }}
            >
              <span className="text-zinc-900 dark:text-zinc-50">Home</span>
              <span className="text-primary">Analyzer</span>
            </span>
          </Link>
          <Link
            href="/login"
            className="text-sm text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-50"
          >
            Sign in →
          </Link>
        </div>
      </header>

      <main className="mx-auto w-full max-w-3xl px-5 py-12 flex-1">
        <div className="space-y-3 mb-12">
          <h1
            className="text-4xl font-bold tracking-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Tour smarter.
          </h1>
          <p className="text-lg text-zinc-600 dark:text-zinc-400">
            Live notes during every house tour, a clear written brief
            after, and an easy way to compare everything you&apos;ve seen.
            Built for buyers, renters, and the people helping them decide.
          </p>
        </div>

        <div className="space-y-14">
          {sections.map((section) => (
            <section key={section.heading} className="space-y-5">
              <div className="space-y-1">
                <h2
                  className="text-2xl font-semibold tracking-tight"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {section.heading}
                </h2>
                {section.blurb ? (
                  <p className="text-sm text-zinc-600 dark:text-zinc-400">
                    {section.blurb}
                  </p>
                ) : null}
              </div>
              <ul className="grid gap-3 sm:grid-cols-2">
                {section.features.map((f) => {
                  const Icon = f.icon;
                  return (
                    <li
                      key={f.title}
                      className="flex gap-3 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 p-4"
                    >
                      <span className="shrink-0 inline-flex items-center justify-center size-9 rounded-lg bg-primary/10 text-primary">
                        <Icon className="size-4.5" strokeWidth={2.25} />
                      </span>
                      <div className="min-w-0">
                        <h3 className="font-semibold leading-tight">
                          {f.title}
                        </h3>
                        <p className="text-sm text-zinc-600 dark:text-zinc-400 mt-1 leading-snug">
                          {f.body}
                        </p>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>

        <div className="mt-16 rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 p-6 text-center">
          <h3
            className="text-xl font-semibold tracking-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Ready to tour?
          </h3>
          <p className="text-sm text-zinc-600 dark:text-zinc-400 mt-1">
            Sign in with an emailed link — no password to remember.
          </p>
          <Link
            href="/login"
            className="inline-block mt-4 rounded-lg bg-primary text-primary-foreground px-5 py-2.5 text-sm font-semibold hover:opacity-90 transition-opacity"
          >
            Sign in
          </Link>
        </div>
      </main>

      <footer className="border-t border-zinc-200 dark:border-zinc-800 mt-12">
        <div className="mx-auto max-w-3xl px-5 py-6 text-xs text-zinc-500">
          HomeAnalyzer
        </div>
      </footer>
    </div>
  );
}
