import {
  Camera,
  CheckCircle2,
  Compass,
  DollarSign,
  Eye,
  GitCompare,
  Home as HomeIcon,
  Mail,
  MapPin,
  Mic,
  Radio,
  Shield,
  Sparkles,
  Trash2,
  Users,
  Video,
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
    heading: "Tour with your family watching live, from anywhere",
    blurb:
      "House hunting often happens with one person on the ground and the other a thousand miles away. HomeAnalyzer brings them along.",
    features: [
      {
        icon: Radio,
        title: "A quiet bot joins the Zoom",
        body: "Tap Start Tour and a silent assistant called Tour Notes joins your Zoom call. It listens and watches — your spouse, your mom, your agent, anyone you invite can hop on Zoom too and see and hear the whole walkthrough.",
      },
      {
        icon: Mic,
        title: "Live transcript as you talk",
        body: "Words show up on the screen seconds after they're spoken — for the buyer holding the phone, for the partner watching from home, for anyone trying to follow what the agent just said about the roof.",
      },
      {
        icon: Eye,
        title: "Notes that organize themselves",
        body: "As the conversation unfolds, observations populate automatically — categorized by hazard, concern, layout, condition, positive features, and what the agent specifically said. No clipboard, no remembering to jot it down.",
      },
      {
        icon: Mail,
        title: "Auto-emailed when the tour starts",
        body: "Everyone you've invited gets an email with the Zoom link the moment you tap Start. They join in one tap — no password, no fumbling.",
      },
    ],
  },
  {
    heading: "Catch what you'd miss in the moment",
    blurb:
      "You can't look at everything at once. The app keeps watching while you're focused.",
    features: [
      {
        icon: Video,
        title: "It looks at the video, too",
        body: "After the tour, the app reviews the recording frame by frame and surfaces visual details no one called out — the water stain on a ceiling, the chip in the cabinet, the peeling paint behind the door. Things you'd notice on the second walkthrough, but caught on the first.",
      },
      {
        icon: CheckCircle2,
        title: "Audio and visual notes side by side",
        body: "Notes from what was said and notes from what was seen show up together. If the agent mentions a leak and the camera caught it too, you see one entry backed by both — not duplicates.",
      },
    ],
  },
  {
    heading: "A clear brief at the end of every tour",
    blurb:
      "Within a minute or two of finishing, you have a written summary you can read on the drive to the next property.",
    features: [
      {
        icon: Sparkles,
        title: "Executive summary, concerns, deal-breakers, score",
        body: "A short, scannable post-tour brief: what shape this house is in, what should give you pause, what would disqualify it, what's genuinely great, and questions worth asking before an offer. Plus a 0–10 score so you can rank at a glance.",
      },
      {
        icon: GitCompare,
        title: "Compare any houses, anytime",
        body: "Pick a few houses — even from different tours — and ask anything in plain English: \"Which one had the best kitchen for kids?\", \"Rank these by how much work they need.\" You get a written answer that cites the houses by name.",
      },
      {
        icon: DollarSign,
        title: "Sale or rent, framed for the right decision",
        body: "Mark a property as for sale or for rent and the brief adapts — resale considerations and offer strategy for buyers, lease terms and landlord notes for renters.",
      },
    ],
  },
  {
    heading: "Tour solo when Zoom isn't an option",
    features: [
      {
        icon: HomeIcon,
        title: "Just record audio and upload",
        body: "Some sellers and agents won't be comfortable with a Zoom call. No problem — record audio on your phone with any voice memo app, upload it when you're done, and the same brief, observations, and comparison work the same way.",
      },
    ],
  },
  {
    heading: "Adding a house should take ten seconds",
    features: [
      {
        icon: MapPin,
        title: "Use my location",
        body: "Standing on the front porch? Tap one button to fill in the address from your phone's location. Edit if it's slightly off, then move on.",
      },
      {
        icon: Camera,
        title: "Curb appeal photo",
        body: "Snap a quick exterior shot from the iPhone camera right in the form. Helps you remember which one was \"the one with the blue shutters\" three days later.",
      },
      {
        icon: Compass,
        title: "One-tap listing search",
        body: "Once the address is filled in, search Zillow, Redfin, or Google with one tap to grab the MLS link, see the photos, or pull up neighborhood stats — without retyping anything.",
      },
    ],
  },
  {
    heading: "Bring your team along",
    features: [
      {
        icon: Users,
        title: "One-tap email invites",
        body: "Invite your spouse, partner, parent, agent, or a friend whose opinion you trust. They click the email link and they're in — no password, no signup screen, no \"please verify your email\" dance.",
      },
      {
        icon: Shield,
        title: "Roles that match real life",
        body: "Buyer, partner, agent, friend & family. Everyone sees the same observations, briefs, and the comparison view across all the houses you've toured together.",
      },
    ],
  },
  {
    heading: "Built to keep things tidy",
    features: [
      {
        icon: Trash2,
        title: "Swipe to delete, fully",
        body: "Swipe a tour or a house off the list and everything goes with it — recordings, observations, photos. No leftover clutter from places you've ruled out.",
      },
      {
        icon: Shield,
        title: "Privacy-conscious",
        body: "Your recordings live in your private storage. Invitees only see the tours you specifically share with them. Nothing's public.",
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
            HomeAnalyzer is for the buyer or renter walking through five
            houses in a week, the partner watching from another state, and
            the agent helping them make a decision they can live with.
            Live notes during the tour, a clear written brief after, and an
            easy way to compare every house you&apos;ve seen.
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
