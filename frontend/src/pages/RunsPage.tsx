import { useCallback, useEffect, useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import DeleteIcon from "@mui/icons-material/Delete";
import DeleteSweepIcon from "@mui/icons-material/DeleteSweep";

import { api } from "../api";
import type { Run } from "../types";
import ConfirmDialog from "../components/ConfirmDialog";

const STATUS_COLOR: Record<string, "success" | "warning" | "error" | "info"> = {
  success: "success",
  partial: "warning",
  error: "error",
  running: "info",
};

function duration(run: Run): string {
  const seconds = run.details.duration_seconds;
  if (seconds === undefined) return "—";
  return seconds < 60 ? `${seconds.toFixed(0)}s` : `${(seconds / 60).toFixed(1)}m`;
}

export default function RunsPage({ refreshKey }: { refreshKey: number }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Run | null>(null);
  const [clearAllOpen, setClearAllOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRuns(await api.runs());
    } catch (loadError) {
      setError((loadError as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  if (loading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Stack spacing={2}>
      {error && <Alert severity="error">{error}</Alert>}
      {notice && (
        <Alert severity="success" onClose={() => setNotice(null)}>
          {notice}
        </Alert>
      )}
      {runs.length === 0 && (
        <Alert severity="info">No runs yet. Use "Run now" or wait for the daily scan.</Alert>
      )}

      {runs.length > 0 && (
        <Stack direction="row" justifyContent="flex-end">
          <Button
            size="small"
            color="error"
            startIcon={<DeleteSweepIcon />}
            onClick={() => setClearAllOpen(true)}
          >
            Clear run history
          </Button>
        </Stack>
      )}

      <Paper>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Started</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Trigger</TableCell>
                <TableCell align="right">Fetched</TableCell>
                <TableCell align="right">New</TableCell>
                <TableCell align="right">Seen before</TableCell>
                <TableCell align="right">Off target</TableCell>
                <TableCell align="right">German</TableCell>
                <TableCell align="right">Low similarity</TableCell>
                <TableCell align="right">Scored</TableCell>
                <TableCell align="right">Passed</TableCell>
                <TableCell align="right">Took</TableCell>
                <TableCell align="right" sx={{ width: 56 }} />
              </TableRow>
            </TableHead>
            <TableBody>
              {runs.map((run) => (
                <TableRow key={run.id} hover>
                  <TableCell>{new Date(run.started_at).toLocaleString()}</TableCell>
                  <TableCell>
                    <Chip size="small" label={run.status} color={STATUS_COLOR[run.status] ?? "default"} />
                  </TableCell>
                  <TableCell>{run.trigger}</TableCell>
                  <TableCell align="right">{run.fetched}</TableCell>
                  <TableCell align="right">{run.new_jobs}</TableCell>
                  <TableCell align="right">{run.duplicates}</TableCell>
                  <TableCell align="right">{run.details.off_target ?? "—"}</TableCell>
                  <TableCell align="right">{run.language_dropped}</TableCell>
                  <TableCell align="right">{run.similarity_dropped}</TableCell>
                  <TableCell align="right">{run.scored}</TableCell>
                  <TableCell align="right">{run.passed}</TableCell>
                  <TableCell align="right">{duration(run)}</TableCell>
                  <TableCell align="right">
                    <Tooltip
                      title={
                        run.status === "running"
                          ? "This run is still going"
                          : `Delete this run and the ${run.new_jobs} job(s) it found`
                      }
                    >
                      <span>
                        <IconButton
                          size="small"
                          disabled={run.status === "running"}
                          onClick={() => setPendingDelete(run)}
                        >
                          <DeleteIcon fontSize="inherit" />
                        </IconButton>
                      </span>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      {runs
        .filter((run) => run.errors.length > 0 || (run.details.notes ?? []).length > 0)
        .map((run) => (
          <Accordion key={`detail-${run.id}`}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography>
                Run {run.id} · {new Date(run.started_at).toLocaleString()} ·{" "}
                {run.errors.length > 0 ? `${run.errors.length} error(s)` : "notes"}
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={1}>
                {(run.details.notes ?? []).map((note) => (
                  <Alert key={note} severity="info">
                    {note}
                  </Alert>
                ))}
                {run.errors.map((message) => (
                  <Alert key={message} severity="error">
                    {message}
                  </Alert>
                ))}
                {run.details.per_source && (
                  <Typography variant="body2" color="text.secondary">
                    Per source:{" "}
                    {Object.entries(run.details.per_source)
                      .map(([name, count]) => `${name} ${count}`)
                      .join(" · ")}
                  </Typography>
                )}
                {run.details.off_target_reasons &&
                  Object.keys(run.details.off_target_reasons).length > 0 && (
                    <Typography variant="body2" color="text.secondary">
                      Title filter dropped {run.details.off_target ?? 0}:{" "}
                      {Object.entries(run.details.off_target_reasons)
                        .map(([reason, count]) => `${reason} (${count})`)
                        .join(" · ")}
                    </Typography>
                  )}
                <Typography variant="body2" color="text.secondary">
                  {run.details.model && `Model: ${run.details.model}`}
                  {run.details.embedding_backend &&
                    ` · Embeddings: ${run.details.embedding_backend}`}
                  {run.details.germany_dropped !== undefined &&
                    ` · Dropped as non-German: ${run.details.germany_dropped}`}
                  {run.details.off_target !== undefined &&
                    ` · Off target: ${run.details.off_target}`}
                  {run.details.similarity_range?.length === 2 &&
                    ` · Similarity range: ${run.details.similarity_range[0]} to ${run.details.similarity_range[1]}`}
                </Typography>
              </Stack>
            </AccordionDetails>
          </Accordion>
        ))}

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete this run?"
        message={
          pendingDelete
            ? `The run from ${new Date(pendingDelete.started_at).toLocaleString()} goes, and so do the ` +
              `${pendingDelete.new_jobs} job(s) it first found - including any you marked applied. ` +
              "Jobs an earlier run had already seen stay."
            : ""
        }
        onCancel={() => setPendingDelete(null)}
        onConfirm={async () => {
          if (!pendingDelete) return;
          const result = await api.deleteRun(pendingDelete.id);
          setPendingDelete(null);
          setNotice(`Deleted the run and ${result.deleted_jobs} job(s).`);
          await load();
        }}
      />

      <ConfirmDialog
        open={clearAllOpen}
        title="Clear the whole run history?"
        message={
          `All ${runs.length} run(s) go, and every job they brought in goes with them. ` +
          "Jobs stored outside a run stay - delete those on the Jobs tab."
        }
        confirmLabel="Clear history"
        onCancel={() => setClearAllOpen(false)}
        onConfirm={async () => {
          const result = await api.deleteAllRuns();
          setClearAllOpen(false);
          setNotice(`Deleted ${result.deleted_runs ?? 0} run(s) and ${result.deleted_jobs} job(s).`);
          await load();
        }}
      />
    </Stack>
  );
}
