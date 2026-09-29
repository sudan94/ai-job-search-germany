import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Chip,
  LinearProgress,
  Paper,
  Stack,
  Tooltip,
  Typography,
} from "@mui/material";
import NotificationsActiveIcon from "@mui/icons-material/NotificationsActive";

import { api } from "../api";
import { STATUS_LABELS, type Job, type Stats, type Status } from "../types";
import { scoreColor } from "../theme";
import { daysSince, formatDay, isDue } from "../dates";
import JobDrawer from "../components/JobDrawer";

/** The statuses that make up an application's life after triage. */
const COLUMNS: { status: Status; hint: string }[] = [
  { status: "interested", hint: "Worth applying to" },
  { status: "applied", hint: "Sent, waiting to hear back" },
  { status: "rejected", hint: "The company said no" },
];

interface Props {
  refreshKey: number;
}

function JobCard({
  job,
  passMark,
  onOpen,
}: {
  job: Job;
  passMark: number;
  onOpen: () => void;
}) {
  const application = job.application;
  const due = application.status !== "rejected" && isDue(application.follow_up_date);
  const appliedAgo = daysSince(application.applied_date);

  return (
    <Paper
      variant="outlined"
      draggable
      onDragStart={(event) => {
        event.dataTransfer.setData("text/plain", String(job.id));
        event.dataTransfer.effectAllowed = "move";
      }}
      onClick={onOpen}
      sx={{
        p: 1.5,
        cursor: "grab",
        borderColor: due ? "warning.main" : undefined,
        "&:hover": { bgcolor: "action.hover" },
      }}
    >
      <Stack direction="row" spacing={1} alignItems="flex-start">
        <Box sx={{ flexGrow: 1, minWidth: 0 }}>
          <Typography variant="body2" fontWeight={600} noWrap title={job.title}>
            {job.title}
          </Typography>
          <Typography variant="caption" color="text.secondary" noWrap component="div">
            {job.company || "Unnamed company"}
            {job.location ? ` · ${job.location}` : ""}
          </Typography>
        </Box>
        {job.analysis?.score !== null && job.analysis?.score !== undefined && (
          <Chip size="small" label={job.analysis.score} color={scoreColor(job.analysis.score, passMark)} />
        )}
      </Stack>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
        {appliedAgo !== null && (
          <Typography variant="caption" color="text.secondary">
            Applied {appliedAgo === 0 ? "today" : `${appliedAgo}d ago`}
          </Typography>
        )}
        {application.follow_up_date && application.status !== "rejected" && (
          <Tooltip title="Follow-up date">
            <Chip
              size="small"
              icon={<NotificationsActiveIcon />}
              color={due ? "warning" : "default"}
              variant={due ? "filled" : "outlined"}
              label={formatDay(application.follow_up_date)}
            />
          </Tooltip>
        )}
        {application.contact && (
          <Typography variant="caption" color="text.secondary" noWrap title={application.contact}>
            {application.contact}
          </Typography>
        )}
      </Stack>
    </Paper>
  );
}

export default function TrackerPage({ refreshKey }: Props) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [dropTarget, setDropTarget] = useState<Status | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, statsResult] = await Promise.all([
        api.jobs({
          status: COLUMNS.map((column) => column.status),
          sort: "status_changed_at",
          order: "desc",
          limit: 500,
        }),
        api.stats(),
      ]);
      setJobs(list.items);
      setStats(statsResult);
    } catch (loadError) {
      setError((loadError as Error).message);
    } finally {
      setLoading(false);
    }
  }, [refreshKey]);

  useEffect(() => {
    load();
  }, [load]);

  const byStatus = useMemo(() => {
    const groups: Record<string, Job[]> = {};
    COLUMNS.forEach((column) => (groups[column.status] = []));
    jobs.forEach((job) => groups[job.application.status]?.push(job));
    // Anything due for a follow-up floats to the top of its column.
    Object.values(groups).forEach((group) =>
      group.sort(
        (a, b) =>
          Number(isDue(b.application.follow_up_date)) - Number(isDue(a.application.follow_up_date)),
      ),
    );
    return groups;
  }, [jobs]);

  const move = async (jobId: number, status: Status) => {
    const job = jobs.find((item) => item.id === jobId);
    if (!job || job.application.status === status) return;
    // Optimistic: the card moves now, and a failed call puts it back on reload.
    setJobs((current) =>
      current.map((item) =>
        item.id === jobId ? { ...item, application: { ...item.application, status } } : item,
      ),
    );
    try {
      await api.setStatus(jobId, status);
    } catch (moveError) {
      setError((moveError as Error).message);
    }
    load();
  };

  const passMark = stats?.min_score ?? 65;

  return (
    <Stack spacing={2}>
      <Typography variant="body2" color="text.secondary">
        Your applications after triage. Drag a card to another column to change its status, or
        click it to set dates, a contact and notes. Mark jobs "Interested" on the Jobs tab to bring
        them here.
      </Typography>

      {stats && stats.follow_ups_due > 0 && (
        <Alert severity="warning" icon={<NotificationsActiveIcon />}>
          {stats.follow_ups_due} follow-up{stats.follow_ups_due === 1 ? " is" : "s are"} due. They
          are highlighted and sorted to the top of their column.
        </Alert>
      )}
      {error && <Alert severity="error">{error}</Alert>}
      {loading && <LinearProgress />}

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: `repeat(${COLUMNS.length}, 1fr)` },
          gap: 2,
          alignItems: "start",
        }}
      >
        {COLUMNS.map((column) => {
          const items = byStatus[column.status] ?? [];
          return (
            <Paper
              key={column.status}
              onDragOver={(event) => {
                event.preventDefault();
                setDropTarget(column.status);
              }}
              onDragLeave={() => setDropTarget(null)}
              onDrop={(event) => {
                event.preventDefault();
                setDropTarget(null);
                const id = Number(event.dataTransfer.getData("text/plain"));
                if (id) move(id, column.status);
              }}
              sx={{
                p: 1.5,
                minHeight: 240,
                bgcolor: dropTarget === column.status ? "action.selected" : "grey.50",
                transition: "background-color 120ms",
              }}
            >
              <Stack direction="row" alignItems="baseline" spacing={1} sx={{ mb: 0.5 }}>
                <Typography variant="subtitle1" fontWeight={600}>
                  {STATUS_LABELS[column.status]}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {items.length}
                </Typography>
              </Stack>
              <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 1.5 }}>
                {column.hint}
              </Typography>
              <Stack spacing={1}>
                {items.map((job) => (
                  <JobCard key={job.id} job={job} passMark={passMark} onOpen={() => setSelected(job.id)} />
                ))}
                {!loading && items.length === 0 && (
                  <Typography variant="body2" color="text.secondary" sx={{ py: 2, textAlign: "center" }}>
                    Nothing here.
                  </Typography>
                )}
              </Stack>
            </Paper>
          );
        })}
      </Box>

      <JobDrawer
        jobId={selected}
        onClose={() => setSelected(null)}
        onChanged={load}
        llmEnabled={stats?.llm_enabled ?? false}
        passMark={passMark}
      />
    </Stack>
  );
}
