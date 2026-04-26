export type Tour = {
  id: string;
  owner_user_id: string;
  name: string;
  location: string | null;
  zoom_pmr_url: string | null;
  status: "planning" | "active" | "completed";
  created_at: string;
};

export type Me = {
  id: string;
  email: string;
  name: string | null;
  default_zoom_url: string | null;
};

export type House = {
  id: string;
  tour_id: string;
  address: string;
  list_price: number | null;
  sqft: number | null;
  beds: number | null;
  baths: number | null;
  listing_url: string | null;
  scheduled_at: string | null;
  status: "upcoming" | "touring" | "synthesizing" | "completed";
  overall_score: number | null;
  overall_notes: string | null;
  bot_id: string | null;
  current_room: string | null;
  audio_url: string | null;
  video_url: string | null;
  synthesis_md: string | null;
};

export type ObservationCategory =
  | "layout"
  | "condition"
  | "hazard"
  | "positive"
  | "concern"
  | "agent_said"
  | "partner_said";

export type Observation = {
  id: string;
  house_id: string;
  user_id: string | null;
  room: string | null;
  category: ObservationCategory;
  content: string;
  severity: "info" | "warn" | "critical" | null;
  source: "manual" | "transcript" | "photo_analysis";
  created_at: string;
  recall_timestamp: number | null;
};
