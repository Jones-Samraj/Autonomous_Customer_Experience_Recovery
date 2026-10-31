export type Severity = 'critical' | 'high' | 'medium' | 'low'
export type Role = 'viewer' | 'analyst' | 'approver' | 'admin'

export interface User { id: number; email: string; full_name: string; role: Role }

export interface Issue {
  id: number; code: string; title: string; description: string; category: string; aspect: string; status: string; severity: Severity
  severity_score: number; detection_confidence: number; support_count: number; duplicate_count: number; growth_rate: number
  kpi_name: string | null; baseline_rate: number | null; current_rate: number | null; first_detected_at: string | null; onset_at: string | null
  iteration: number; reopen_count: number; updated_at: string | null
  top_hypothesis?: { title: string; confidence: number; status: string } | null
  pending_approvals?: number; clusters?: number; sparkline?: number[]
  severity_breakdown?: { components: Record<string, number>; weights: Record<string, number> }
  stats?: any; kpi_series?: { date: string; n: number; k: number; rate: number }[]
  business_timeline?: TimelineItem[]
}

export interface TimelineItem { at: string | null; kind: string; title: string; detail?: string; status?: string; run_id?: string }

export interface Evidence {
  id: number; relation: 'supports' | 'contradicts' | 'context'; kind: string; summary: string; weight: number; payload: any
  signal_id: number | null; event_id: number | null; release_id: number | null
}

export interface Hypothesis {
  id: number; issue_id: number; iteration: number; rank: number; title: string; cause_type: string; statement: string; narrative: string | null
  confidence: number; evidence_quality: number; quality_label: string; status: string; causal_claim: string
  alternatives: { title: string; confidence: number; cause_type: string; note?: string }[]; additional_data_needed: string[]
  features: Record<string, any>; scope: Record<string, any>
  supporting_evidence: Evidence[]; contradicting_evidence: Evidence[]; context_evidence: Evidence[]
}

export interface Intervention {
  id: number; code: string; issue_id: number; iteration: number; type: string; title: string; description: string; role: string; status: string
  verification_status: string; requires_approval: boolean; is_consequential: boolean; expected_impact: number; cost_inr: number; execution_hours: number
  customer_benefit: number; business_risk: number; feasibility: number; confidence: number; reversibility: number; utility: number; rank: number
  is_recommended: boolean; rationale: string; target_hypothesis_id: number | null; params: any; superseded: boolean
  created_at: string | null; approved_at: string | null; executed_at: string | null; verified_at: string | null
  criteria?: { normalised: Record<string, number>; weighted_contribution: Record<string, number>; weights: Record<string, number>; addresses: any[] } | null
  issue?: { id: number; code: string; title: string; iteration: number }
  execution_logs?: ExecLog[]; tickets?: any[]; approvals?: Approval[]; target_hypothesis?: Hypothesis | null
}

export interface ExecLog { id: number; action: string; system: string; idempotency_key: string; attempt: number; status: string; request: any; response: any; error: string | null; duration_ms: number; created_at: string }

export interface Approval {
  id: number; status: string; requested_at: string; decided_at: string | null; decided_by: number | null; decided_by_name?: string | null; comment: string | null; summary: any
  intervention: Intervention; issue?: { id: number; code: string; title: string; severity: Severity; category: string }; target_hypothesis?: Hypothesis | null
  execution?: string | null
}

export interface ImpactEstimate {
  metric: string; label: string; value: number | null; unit: string; kind: 'measured' | 'estimated'; formula: string; inputs: any; assumptions: string[]
  ci_low: number | null; ci_high: number | null; calculated_at: string
}

export interface AgentRun {
  id: number; run_id: string; issue_id?: number | null; issue_code?: string | null; agent: string; task: string; input_summary: any; reasoning_summary: string
  output_summary: any; status: string; attempt: number; started_at: string; duration_ms: number | null; error: string | null; llm_cost_usd?: number; llm_tokens?: number
}

export interface Investigation {
  issue: Issue; status: string; stage: string; iteration: number; hypotheses: Hypothesis[]; previous_hypotheses: Record<string, any[]>
  segmentation: Segmentation | null; impact: ImpactEstimate[]; interventions: Intervention[]; history: AgentRun[]; timeline: TimelineItem[]; approvals: Approval[]
}

export interface SegmentRow { dimension: string; label: string; value: string; customers: number; affected: number; rate: number; lift: number; p_adj: number; severity: string; pattern: string; share_of_affected: number }
export interface Segmentation {
  affected_customers: number; active_customers: number; affected_rate: number; segments: SegmentRow[]
  predefined: { value: string; name?: string; customers: number; affected: number; rate: number; lift: number; revenue_exposure_30d: number; severity: string }[]
  geography: { value: string; customers: number; affected: number; rate: number; lift: number; revenue_exposure_30d: number; severity: string }[]
  products: { value: string; bad_events: number }[]; suppressed_groups: number; k_anonymity_min_group: number; privacy_notes: string[]; revenue_exposure_30d: number
}

export interface KpiSeries {
  code: string; name: string; unit: string; direction: string; target: number | null; latest: number | null; baseline: number | null
  series: { date: string; value: number }[]
}

export interface Notice { id: number; level: string; title: string; body: string; link: string | null; is_read: boolean; created_at: string }
