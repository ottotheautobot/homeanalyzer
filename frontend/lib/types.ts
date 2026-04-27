export type Tour = {
  id: string;
  owner_user_id: string;
  name: string;
  location: string | null;
  zoom_pmr_url: string | null;
  status: "planning" | "active" | "completed";
  created_at: string;
};

export type TourSummary = Tour & {
  house_count: number;
  completed_count: number;
  in_progress_count: number;
  avg_score: number | null;
  last_activity_at: string | null;
};

export type Me = {
  id: string;
  email: string;
  name: string | null;
  default_zoom_url: string | null;
};

export type TourInvite = {
  id: string;
  tour_id: string;
  email: string;
  role: string | null;
  expires_at: string;
  accepted_at: string | null;
};

export type Transcript = {
  id: string;
  house_id: string;
  bot_id: string;
  speaker: string | null;
  text: string;
  start_seconds: number;
  end_seconds: number | null;
  processed: boolean;
};

export type House = {
  id: string;
  tour_id: string;
  address: string;
  list_price: number | null;
  price_kind: "sale" | "rent" | null;
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
  tour_started_at: string | null;
  audio_url: string | null;
  video_url: string | null;
  video_duration_seconds: number | null;
  photo_url: string | null;
  photo_signed_url: string | null;
  synthesis_md: string | null;
  floor_plan_json: FloorPlan | null;
  measured_floor_plan_json: MeasuredFloorPlan | null;
  measured_floor_plan_status: "pending" | "ready" | "failed" | null;
  measured_floor_plan_error: string | null;
  measured_floor_plan_started_at: string | null;
};

export type MeasuredFloorPlanRoom = {
  id: string;
  label: string;
  polygon_m: Array<[number, number]>;
  width_m: number;
  depth_m: number;
  confidence: number;
  sample_count?: number;
  source?: "wall-points" | "camera-path" | string;
};

export type MeasuredFloorPlanDoor = {
  from: string;
  to: string;
  x_m: number;
  z_m: number;
};

export type MeasuredFloorPlan = {
  rooms: MeasuredFloorPlanRoom[];
  doors: MeasuredFloorPlanDoor[];
  scale_m_per_unit: number;
  confidence: "low" | "medium" | "high";
  notes: string | null;
  model_version: string;
  stats: Record<string, unknown> | null;
};

export type FloorPlanRoom = {
  id: string;
  label: string;
  entered_at: number | null;
  exited_at: number | null;
  features: string[];
  width_ft: number | null;
  depth_ft: number | null;
};

export type FloorPlanDoor = {
  from: string;
  to: string;
  via: "sequence" | "transcript";
};

export type FloorPlan = {
  rooms: FloorPlanRoom[];
  doors: FloorPlanDoor[];
  confidence: "low" | "medium" | "high";
  notes: string | null;
  model_version: string;
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
