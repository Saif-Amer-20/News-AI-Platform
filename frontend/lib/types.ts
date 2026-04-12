/* ── Shared domain types for the NewsIntel frontend ────────── */

/* ── Events ────────────────────────────────────────────────── */
export type EventSummary = {
  id: number;
  title: string;
  description: string;
  event_type: string;
  location_name: string;
  location_country: string;
  importance_score: number;
  confidence_score: number;
  conflict_flag: boolean;
  story_count: number;
  source_count: number;
  first_reported_at: string;
  last_reported_at: string;
  narrative_conflicts?: string;
};

export type EventDetail = EventSummary & {
  article_count: number;
};

export type EventExplain = {
  event_id: number;
  event_title: string;
  event_type: string;
  description: string;
  confidence_factors: {
    source_count: number;
    story_count: number;
    confidence_score: number;
    geo_confidence: number;
    conflict_flag: boolean;
    narrative_conflicts: string;
  };
  source_correlation: unknown;
  story_chain: {
    story_id: number;
    title: string;
    story_key: string;
    article_count: number;
    importance_score: number;
    articles: {
      id: number;
      title: string;
      source__name: string;
      quality_score: number;
      importance_score: number;
      published_at: string;
    }[];
  }[];
  timeline_json: unknown;
};

export type EventTimeline = {
  event_id: number;
  event_title: string;
  first_reported_at: string;
  last_reported_at: string;
  intelligence_timeline: unknown[];
  article_timeline: {
    id: number;
    title: string;
    published_at: string;
    source__name: string;
    importance_score: number;
  }[];
};

export type EventEntity = {
  entity_id: number;
  entity_name: string;
  entity_type: string;
  entity_country: string;
  mention_count: number;
  avg_relevance: number;
};

export type EventSource = {
  source_id: number;
  name: string;
  source_type: string;
  country: string;
  trust_score: number;
  article_count: number;
  earliest: string;
  latest: string;
};

export type RelatedEvent = {
  event_id: number;
  title: string;
  event_type: string;
  location_name: string;
  country: string;
  importance: number;
  relation: string;
  distance?: number;
};

/* ── Alerts ────────────────────────────────────────────────── */
export type AlertSummary = {
  id: number;
  title: string;
  summary: string;
  alert_type: string;
  severity: string;
  status: string;
  source__name: string;
  topic__name: string;
  triggered_at: string;
};

export type AlertDetail = AlertSummary & {
  description: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  event?: number;
  article?: number;
};

export type AlertExplain = {
  alert_id: number;
  alert_type: string;
  severity: string;
  rationale: string;
  trigger_data: {
    article?: Record<string, unknown>;
    matched_rules?: unknown;
    rule_details?: unknown;
  };
  context: {
    event?: Record<string, unknown>;
    similar_alerts?: unknown;
  };
  recommended_actions: string[];
};

/* ── Entities ──────────────────────────────────────────────── */
export type EntitySummary = {
  id: number;
  name: string;
  canonical_name?: string;
  entity_type: string;
  country: string;
  description: string;
  article_count: number;
  event_count: number;
  aliases?: string[];
};

export type EntityCoOccurrence = {
  co_entity_id: number;
  co_entity_name: string;
  co_entity_type: string;
  co_entity_country: string;
  shared_articles: number;
  avg_relevance: number;
};

export type EntityMention = {
  article_id: number;
  article_title: string;
  source: string;
  published_at: string;
  relevance_score: number;
  mention_count: number;
  context_snippet: string;
};

/* ── Cases ─────────────────────────────────────────────────── */
export type CaseSummary = {
  id: number;
  title: string;
  description: string;
  status: string;
  priority: string;
  classification?: string;
  created_at: string;
  updated_at: string;
  opened_at: string;
  due_at?: string;
  article_count?: number;
  entity_count?: number;
  event_count?: number;
  note_count?: number;
  member_count?: number;
};

export type CaseNote = {
  id: number;
  text: string;
  note_type?: string;
  created_at: string;
  updated_at: string;
  author?: string;
};

export type CaseReference = {
  id: number;
  reference_type: string;
  reference_id: number;
  title: string;
  notes: string;
  added_at: string;
};

export type CaseTimelineEntry = {
  ts: string;
  type: string;
  title: string;
  detail?: string;
  actor?: string;
  object_id?: number;
  note_id?: number;
  reference_type?: string;
};

export type CaseDetailFull = CaseSummary & {
  notes: CaseNote[];
  alerts: { id: number; title: string; severity: string }[];
  events: { id: number; title: string; event_type: string }[];
  entities: { id: number; name: string; entity_type: string }[];
  articles: { id: number; title: string; source_name: string }[];
  references: CaseReference[];
  members: { id: number; user: string; role: string }[];
};

/* ── Timeline ──────────────────────────────────────────────── */
export type TimelineEntry = {
  ts: string;
  type: string;
  id: number;
  title: string;
  event_type?: string;
  location?: string;
  country?: string;
  importance?: number;
  confidence?: number;
  conflict?: boolean;
  stories?: number;
  sources?: number;
  source?: string;
  alert_type?: string;
  severity?: string;
  status?: string;
};

/* ── Map ───────────────────────────────────────────────────── */
export type MapFeature = {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: {
    id: number;
    title: string;
    event_type: string;
    location_name: string;
    country: string;
    importance: number;
    confidence: number;
    conflict: boolean;
    stories: number;
    sources: number;
    first_reported: string;
    last_reported: string;
  };
};

export type HeatPoint = { lat: number; lon: number; weight: number; count: number };

export type ClusterPoint = {
  location_country: string;
  event_count: number;
  avg_lat: number;
  avg_lon: number;
  avg_importance: number;
  conflict_count: number;
};

/* ── Utility maps ──────────────────────────────────────────── */
export const SEVERITY_BADGE: Record<string, string> = {
  critical: "badge-red",
  high: "badge-amber",
  medium: "badge-blue",
  low: "badge-gray",
};

export const STATUS_BADGE: Record<string, string> = {
  open: "badge-red",
  acknowledged: "badge-amber",
  resolved: "badge-green",
  dismissed: "badge-gray",
  closed: "badge-green",
  escalated: "badge-red",
};

export const PRIORITY_BADGE: Record<string, string> = {
  critical: "badge-red",
  high: "badge-amber",
  medium: "badge-blue",
  low: "badge-gray",
};

export const EVENT_TYPES = [
  "political", "economic", "military", "social", "environmental",
  "legal", "health", "technology", "diplomatic", "humanitarian",
];

export const ENTITY_TYPES = [
  "person", "organization", "location", "facility", "event", "product", "other",
];

/* ── Entity Explain ────────────────────────────────────────── */
export type EntityExplain = {
  entity_id: number;
  entity_name: string;
  entity_type: string;
  description: string;
  importance_factors: {
    article_count: number;
    event_count: number;
    co_occurrence_count: number;
    mention_diversity: number;
    avg_relevance: number;
  };
  source_diversity: {
    unique_sources: number;
    source_types: string[];
    countries: string[];
  };
  top_events: { id: number; title: string; event_type: string; importance: number }[];
  top_co_entities: { id: number; name: string; entity_type: string; shared_articles: number }[];
};

/* ── Narrative / Conflict ──────────────────────────────────── */

/* ── Articles ──────────────────────────────────────────────── */
export type ArticleTranslation = {
  id: number;
  language_code: string;
  translated_title: string;
  translated_body: string;
  translation_status: "pending" | "completed" | "failed";
  translated_at: string | null;
  provider: string;
  error_message: string;
  created_at: string;
};

export type ArticleAISummary = {
  id: number;
  summary: string;
  predictions: string;
  summary_ar: string;
  predictions_ar: string;
  model_used: string;
  status: "pending" | "completed" | "failed";
  generated_at: string | null;
  error_message: string;
  created_at: string;
};

export type ArticleDetail = {
  id: number;
  title: string;
  normalized_title: string;
  url: string;
  canonical_url: string;
  content: string;
  author: string;
  image_url: string;
  source: number;
  source_name: string;
  story: number | null;
  story_title: string | null;
  published_at: string;
  is_duplicate: boolean;
  content_hash: string;
  quality_score: number;
  importance_score: number;
  matched_rule_labels: string[];
  entities: {
    id: number;
    entity: {
      id: number;
      name: string;
      entity_type: string;
      country: string;
    };
    relevance_score: number;
    mention_count: number;
    context_snippet: string;
  }[];
  matched_topic_names: string[];
  translations: ArticleTranslation[];
  ai_summary: ArticleAISummary | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ArticleRelated = {
  id: number;
  title: string;
  source_name: string;
  published_at: string;
  importance_score: number;
  relation: string;
};

export type ArticleEvent = {
  id: number;
  title: string;
  event_type: string;
  location_name: string;
  location_country: string;
  importance_score: number;
  first_reported_at: string;
};

export type ArticleEntityLink = {
  entity_id: number;
  name: string;
  entity_type: string;
  country: string;
  relevance_score: number;
  mention_count: number;
  context_snippet: string;
};

/* ── Narrative / Conflict ──────────────────────────────────── */
export type NarrativeGroup = {
  narrative_id: number;
  label: string;
  stance: string;
  confidence: number;
  article_count: number;
  sources: { name: string; trust_score: number; country: string }[];
  summary: string;
  key_claims: string[];
};

export type ConflictAnalysis = {
  event_id: number;
  has_conflict: boolean;
  conflict_summary: string;
  narratives: NarrativeGroup[];
};

/* ── Hypothesis System ─────────────────────────────────────── */
export type HypothesisStatus = "draft" | "active" | "supported" | "refuted" | "inconclusive";

export type EvidenceLink = {
  id: string;
  ref_type: "event" | "entity" | "article";
  ref_id: number;
  ref_title: string;
  stance: "supports" | "contradicts" | "neutral";
  strength: number;       // 0-1
  analyst_note: string;
  added_at: string;
};

export type ConfidenceSnapshot = {
  ts: string;
  confidence: number;     // 0-1
  reason: string;
};

export type Hypothesis = {
  id: string;
  case_id: number;
  title: string;
  statement: string;
  status: HypothesisStatus;
  confidence: number;     // 0-1
  evidence: EvidenceLink[];
  confidence_history: ConfidenceSnapshot[];
  created_at: string;
  updated_at: string;
};

export const HYPOTHESIS_STATUS_BADGE: Record<HypothesisStatus, string> = {
  draft: "badge-gray",
  active: "badge-blue",
  supported: "badge-green",
  refuted: "badge-red",
  inconclusive: "badge-amber",
};

/* ── Reasoning Chains ──────────────────────────────────────── */
export type ReasoningNodeType = "event" | "entity" | "narrative" | "hypothesis" | "conclusion";

export type ReasoningNode = {
  id: string;
  type: ReasoningNodeType;
  ref_id?: number;
  label: string;
  detail?: string;
  confidence?: number;
};

export type ReasoningEdge = {
  from: string;
  to: string;
  relation: string;       // "leads_to" | "supports" | "contradicts" | "involves"
};

export type ReasoningChain = {
  id: string;
  case_id: number;
  title: string;
  nodes: ReasoningNode[];
  edges: ReasoningEdge[];
  conclusion?: string;
  created_at: string;
  updated_at: string;
};

/* ── Decision Support ──────────────────────────────────────── */
export type DecisionAction = "monitor" | "escalate" | "verify" | "close";

export type DecisionSuggestion = {
  action: DecisionAction;
  rationale: string;
  confidence_factor: number;
  conflict_factor: number;
  source_diversity_factor: number;
  overall_score: number;
};

export type DecisionRecord = {
  id: string;
  case_id: number;
  action: DecisionAction;
  rationale: string;
  decided_at: string;
  analyst?: string;
};

/* ── Anomaly / Signal Detection ────────────────────────────── */
export type AnomalyType = "spike" | "pattern_break" | "new_actor" | "geographic_shift" | "sentiment_shift";

export type AnomalySignal = {
  id: string;
  type: AnomalyType;
  title: string;
  description: string;
  severity: "low" | "medium" | "high";
  metric_name: string;
  baseline_value: number;
  current_value: number;
  detected_at: string;
  related_events: number[];
  related_entities: number[];
  dismissed: boolean;
};

export const ANOMALY_TYPE_LABELS: Record<AnomalyType, string> = {
  spike: "Volume Spike",
  pattern_break: "Pattern Break",
  new_actor: "New Actor",
  geographic_shift: "Geographic Shift",
  sentiment_shift: "Sentiment Shift",
};

/* ── Structured Notes ──────────────────────────────────────── */
export type StructuredNote = {
  id: string;
  case_id: number;
  text: string;
  note_type: "observation" | "assessment" | "action_item" | "question";
  tags: string[];
  linked_events: number[];
  linked_entities: number[];
  timeline_date?: string;
  created_at: string;
  updated_at: string;
  author?: string;
};

export const NOTE_TYPE_BADGE: Record<string, string> = {
  observation: "badge-blue",
  assessment: "badge-purple",
  action_item: "badge-amber",
  question: "badge-gray",
};

/* ── Case Evolution ────────────────────────────────────────── */
export type CaseEvolutionEntry = {
  ts: string;
  type: "event_added" | "entity_added" | "hypothesis_created" | "hypothesis_updated" |
        "evidence_added" | "decision_made" | "note_added" | "status_changed" | "chain_created";
  title: string;
  detail?: string;
  actor?: string;
  ref_id?: string;
  snapshot?: { confidence?: number; status?: string };
};
