import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Drawer,
  IconButton,
  Link,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";

import { api, type TrackingUpdate } from "../api";
import { STATUSES, STATUS_LABELS, type JobDetail, type TimelineEvent } from "../types";
import { scoreColor, statusColor } from "../theme";
import { addDays, formatDay, formatInstant, fromDay, isDue, toDay } from "../dates";

interface Props {
  jobId: number | null;
  onClose: () => void;
  onChanged: () => void;
  llmEnabled: boolean;
  passMark?: number;
}

function describeEvent(event: TimelineEvent): string {
  if (event.to_status) {
    const from = event.from_status ? STATUS_LABELS[event.from_status] ?? event.from_status : "—";
    const to = STATUS_LABELS[event.to_status] ?? event.to_status;
    return `${from} → ${to}`;
  }
  return "Note";
}

export default function JobDrawer({ jobId, onClose, onChanged, llmEnabled, passMark = 65 }: Props) {
  const [job, setJob] = useState<JobDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [contact, setContact] = useState("");
  const [log, setLog] = useState("");

  const load = useCallback(async (id: number) => {
    setLoading(true);
    setError(null);
    try {
      const detail = await api.job(id);
      setJob(detail);
      setNotes(detail.application.notes ?? "");
      setContact(detail.application.contact ?? "");
    } catch (loadError) {
      setError((loadError as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (jobId === null) {
      setJob(null);
      setLog("");
      return;
    }
    load(jobId);
  }, [jobId, load]);

  const act = async (name: string, action: () => Promise<unknown>) => {
    setBusy(name);
    setError(null);
    try {
      await action();
      if (jobId !== null) await load(jobId);
      onChanged();
    } catch (actionError) {
      setError((actionError as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const track = (name: string, payload: TrackingUpdate) =>
    job ? act(name, () => api.track(job.id, payload)) : Promise.resolve();

  const analysis = job?.analysis;
  const application = job?.application;
  const followUpDue =
    application &&
    isDue(application.follow_up_date) &&
    (application.status === "applied" || application.status === "interested");

  return (
    <Drawer
      anchor="right"
      open={jobId !== null}
      onClose={onClose}
      PaperProps={{ sx: { width: { xs: "100%", md: 720 }, p: 3 } }}
    >
      {loading && !job && (
        <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
          <CircularProgress />
        </Box>
      )}

      {job && application && (
        <Stack spacing={2}>
          <Stack direction="row" alignItems="flex-start" spacing={1}>
            <Box sx={{ flexGrow: 1 }}>
              <Typography variant="h6">{job.title}</Typography>
              <Typography color="text.secondary">
                {job.company} · {job.location || "location not given"} ·{" "}
                {job.publisher ? `${job.publisher} (via JSearch)` : job.source}
              </Typography>
            </Box>
            <IconButton onClick={onClose} size="small">
              <CloseIcon />
            </IconButton>
          </Stack>

          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
            {analysis?.score !== null && analysis?.score !== undefined && (
              <Chip label={`Score ${analysis.score}`} color={scoreColor(analysis.score, passMark)} />
            )}
            {analysis?.similarity !== null && analysis?.similarity !== undefined && (
              <Chip variant="outlined" label={`Similarity ${analysis.similarity.toFixed(3)}`} />
            )}
            <Chip
              label={STATUS_LABELS[application.status] ?? application.status}
              color={statusColor[application.status] ?? "default"}
            />
            {job.remote && <Chip variant="outlined" label="remote" />}
            {job.url && (
              <Link href={job.url} target="_blank" rel="noreferrer" sx={{ display: "flex", gap: 0.5 }}>
                Open posting <OpenInNewIcon fontSize="small" />
              </Link>
            )}
          </Stack>

          {error && <Alert severity="error">{error}</Alert>}

          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {STATUSES.map((status) => (
              <Button
                key={status}
                size="small"
                variant={application.status === status ? "contained" : "outlined"}
                color={status === "rejected" ? "error" : "primary"}
                onClick={() => track(status, { status })}
                disabled={busy !== null || application.status === status}
              >
                {STATUS_LABELS[status]}
              </Button>
            ))}
          </Stack>

          {followUpDue && (
            <Alert severity="warning">
              Follow-up due {formatDay(application.follow_up_date)}. Chase it, then set the next date
              or clear it.
            </Alert>
          )}

          <Box>
            <Typography variant="subtitle1" gutterBottom>
              Tracking
            </Typography>
            <Stack spacing={2}>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }}>
                <TextField
                  label="Applied on"
                  type="date"
                  size="small"
                  InputLabelProps={{ shrink: true }}
                  value={toDay(application.applied_date) ?? ""}
                  onChange={(event) =>
                    track("applied_date", { applied_date: fromDay(event.target.value) })
                  }
                />
                <TextField
                  label="Follow up on"
                  type="date"
                  size="small"
                  InputLabelProps={{ shrink: true }}
                  value={toDay(application.follow_up_date) ?? ""}
                  onChange={(event) =>
                    track("follow_up", { follow_up_date: fromDay(event.target.value) })
                  }
                />
                <Stack direction="row" spacing={0.5}>
                  {[3, 7, 14].map((days) => (
                    <Button
                      key={days}
                      size="small"
                      disabled={busy !== null}
                      onClick={() => track("follow_up", { follow_up_date: fromDay(addDays(days)) })}
                    >
                      +{days}d
                    </Button>
                  ))}
                  {application.follow_up_date && (
                    <Button
                      size="small"
                      color="inherit"
                      disabled={busy !== null}
                      onClick={() => track("follow_up", { follow_up_date: null })}
                    >
                      Clear
                    </Button>
                  )}
                </Stack>
              </Stack>
              <TextField
                label="Contact"
                size="small"
                fullWidth
                value={contact}
                onChange={(event) => setContact(event.target.value)}
                onBlur={() => {
                  if (contact !== (application.contact ?? "")) track("contact", { contact });
                }}
                placeholder="Recruiter or hiring manager, email, phone"
              />
              <TextField
                label="Notes"
                multiline
                minRows={2}
                fullWidth
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                onBlur={() => {
                  if (notes !== (application.notes ?? "")) track("notes", { notes });
                }}
                placeholder="What you sent, salary discussed, anything to remember."
              />
            </Stack>
          </Box>

          <Box>
            <Typography variant="subtitle1" gutterBottom>
              Timeline
            </Typography>
            <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
              <TextField
                size="small"
                fullWidth
                value={log}
                onChange={(event) => setLog(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && log.trim()) {
                    track("log", { log }).then(() => setLog(""));
                  }
                }}
                placeholder="Add an entry, e.g. 'Phone screen with Anna on Tuesday'"
              />
              <Button
                disabled={!log.trim() || busy !== null}
                onClick={() => track("log", { log }).then(() => setLog(""))}
              >
                Add
              </Button>
            </Stack>
            {job.events.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                Nothing yet. Status changes and entries you add appear here.
              </Typography>
            ) : (
              <Stack spacing={0.75}>
                {job.events.map((event) => (
                  <Stack key={event.id} direction="row" spacing={1} alignItems="flex-start">
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      sx={{ minWidth: 130, pt: 0.25 }}
                    >
                      {formatInstant(event.created_at)}
                    </Typography>
                    <Box sx={{ flexGrow: 1 }}>
                      <Typography variant="body2" fontWeight={500}>
                        {describeEvent(event)}
                        {event.actor === "system" && (
                          <Chip size="small" label="system" sx={{ ml: 1 }} variant="outlined" />
                        )}
                      </Typography>
                      {event.note && (
                        <Typography variant="body2" color="text.secondary">
                          {event.note}
                        </Typography>
                      )}
                    </Box>
                    <Tooltip title="Delete entry">
                      <IconButton
                        size="small"
                        disabled={busy !== null}
                        onClick={() => act("event", () => api.deleteEvent(job.id, event.id))}
                      >
                        <DeleteOutlineIcon fontSize="inherit" />
                      </IconButton>
                    </Tooltip>
                  </Stack>
                ))}
              </Stack>
            )}
          </Box>

          <Divider />

          {analysis?.verdict && (
            <Alert severity="info" icon={false}>
              {analysis.verdict}
            </Alert>
          )}

          {(analysis?.matched?.length || analysis?.missing?.length) && (
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <Box sx={{ flex: 1 }}>
                <Typography variant="subtitle2" gutterBottom>
                  Matched
                </Typography>
                <Stack spacing={0.5}>
                  {analysis?.matched?.map((item) => (
                    <Chip key={item} size="small" color="success" variant="outlined" label={item} />
                  ))}
                </Stack>
              </Box>
              <Box sx={{ flex: 1 }}>
                <Typography variant="subtitle2" gutterBottom>
                  Missing
                </Typography>
                <Stack spacing={0.5}>
                  {analysis?.missing?.map((item) => (
                    <Chip key={item} size="small" color="error" variant="outlined" label={item} />
                  ))}
                </Stack>
              </Box>
            </Stack>
          )}

          {analysis && (
            <Box>
              <Typography variant="subtitle2">Language verdict</Typography>
              <Typography variant="body2" color="text.secondary">
                Working language: {analysis.working_language ?? "unknown"} · German required:{" "}
                {analysis.german_required === null ? "unknown" : analysis.german_required ? "yes" : "no"}
                {analysis.language_confidence !== null &&
                  ` · confidence ${(analysis.language_confidence * 100).toFixed(0)}%`}
                {analysis.detected_language && ` · JD detected as ${analysis.detected_language}`}
              </Typography>
              {analysis.language_evidence && (
                <Typography variant="caption" color="text.secondary" sx={{ fontStyle: "italic" }}>
                  “{analysis.language_evidence}”
                </Typography>
              )}
            </Box>
          )}

          <Divider />

          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>
              Job description
            </Typography>
            <Button
              size="small"
              disabled={busy !== null || !llmEnabled}
              onClick={() => act("rescore", () => api.rescore(job.id))}
            >
              {busy === "rescore" ? "Rescoring…" : "Rescore"}
            </Button>
          </Stack>
          <Typography
            variant="body2"
            component="pre"
            sx={{
              whiteSpace: "pre-wrap",
              fontFamily: "inherit",
              bgcolor: "grey.50",
              p: 2,
              borderRadius: 1,
              maxHeight: 420,
              overflow: "auto",
            }}
          >
            {job.description || "This source gave no description text."}
          </Typography>
        </Stack>
      )}
    </Drawer>
  );
}
