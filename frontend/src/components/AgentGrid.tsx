import AgentCard from "./AgentCard";
import type { Agent, AgentId, AgentState } from "../types";

interface AgentGridProps {
  agents: Agent[];
  agentStates: Record<AgentId, AgentState>;
  selected: AgentId | null;
  onSelect: (id: AgentId | null) => void;
}

export default function AgentGrid({ agents, agentStates, selected, onSelect }: AgentGridProps) {
  return (
    <div style={{ padding: 14 }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 10,
        }}
      >
        <span className="panel-header">Agent Pipeline</span>
        <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)" }}>
          BEDROCK&nbsp;·&nbsp;MULTI-AGENT
        </span>
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 8,
        }}
      >
        {agents.map((a) => (
          <AgentCard
            key={a.id}
            agent={a}
            state={agentStates[a.id] ?? "idle"}
            selected={selected === a.id}
            onClick={() => onSelect(selected === a.id ? null : a.id)}
          />
        ))}
      </div>
    </div>
  );
}
