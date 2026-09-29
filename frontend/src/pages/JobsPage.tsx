import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControl,
  IconButton,
  InputLabel,
  LinearProgress,
  MenuItem,
  OutlinedInput,
  Paper,
  Select,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  TableSortLabel,
  TextField,
  Tooltip,
  Typography,
  FormControlLabel,
} from "@mui/material";
import LanguageIcon from "@mui/icons-material/Language";
import NotificationsActiveIcon from "@mui/icons-material/NotificationsActive";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import DeleteIcon from "@mui/icons-material/Delete";
import DeleteSweepIcon from "@mui/icons-material/DeleteSweep";

import { api } from "../api";
import { STATUSES, STATUS_LABELS, type Job, type Stats, type Status } from "../types";
import { scoreColor, statusColor } from "../theme";
import { formatDay, isDue } from "../dates";
import JobDrawer from "../components/JobDrawer";
import ConfirmDialog from "../components/ConfirmDialog";

interface Props {
  refreshKey: number;
}

export default function JobsPage({ refreshKey }: Props) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  const [statuses, setStatuses] = useState<Status[]>(["new", "interested"]);
  const [minScore, setMinScore] = useState<number | "">("");
  // Whether the view opens on matches only is a setting. Everything a run
  // collected but has not scored yet is still in the table behind this switch.
  const [matchesOnly, setMatchesOnly] = useState(true);
  const [followUpsOnly, setFollowUpsOnly] = useState(false);
  const [passMark, setPassMark] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [sort, setSort] = useState("score");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);
  const [pendingDelete, setPendingDelete] = useState<Job | null>(null);
  const [clearAllOpen, setClearAllOpen] = useState(false);

  // The pass mark and the default view live in settings, so they are read once
  // rather than on every reload; `load` waits for them so the first paint is
  // already filtered the way the settings say.
  useEffect(() => {
    api
      .settings()
      .then((loaded) => {
        setPassMark(loaded.min_score);
        setMatchesOnly(loaded.jobs_matches_only_default);
      })
      .catch(() => setPassMark(0));
  }, []);

  const load = useCallback(async () => {
    if (passMark === null) return;
    setLoading(true);
    setError(null);
    try {
      const threshold = minScore === "" ? undefined : Number(minScore);
      const [list, statsResult] = await Promise.all([
        api.jobs({
          status: statuses.length ? statuses : undefined,
          min_score: matchesOnly ? Math.max(passMark, threshold ?? 0) : threshold,
          search: search || undefined,
          follow_up_due: followUpsOnly || undefined,
          remote_only: remoteOnly || undefined,
          sort,
          order,
          limit: rowsPerPage,
          offset: page * rowsPerPage,
        }),
        api.stats(),
      ]);
      setJobs(list.items);
      setTotal(list.total);
      setStats(statsResult);
    } catch (loadError) {
      setError((loadError as Error).message);
    } finally {
      setLoading(false);
    }
  }, [
    statuses,
    minScore,
    matchesOnly,
    followUpsOnly,
    passMark,
    search,
    remoteOnly,
    sort,
    order,
    page,
    rowsPerPage,
    refreshKey,
  ]);

  useEffect(() => {
    const timer = setTimeout(load, search ? 350 : 0); // debounce typing only
    return () => clearTimeout(timer);
  }, [load, search]);

  const summary = useMemo(() => {
    if (!stats) return null;
    return STATUSES.map((status) => ({ status, value: stats.by_status[status] ?? 0 }));
  }, [stats]);

  /** A tile click shows exactly that status, with nothing else hiding rows. */
  const showOnly = (status: Status) => {
    setStatuses([status]);
    setMatchesOnly(false);
    setFollowUpsOnly(false);
    setPage(0);
  };

  const toggleSort = (column: string) => {
    if (sort === column) {
      setOrder(order === "desc" ? "asc" : "desc");
    } else {
      setSort(column);
      setOrder("desc");
    }
  };

  return (
    <Stack spacing={2}>
      {stats && !stats.has_cv && (
        <Alert severity="info">
          No CV on file yet. Upload one on the CV tab, then scoring can run.
        </Alert>
      )}
      {stats && !stats.llm_enabled && (
        <Alert severity="warning">
          OPENAI_API_KEY is not set, so jobs are collected and ranked but not scored.
        </Alert>
      )}

      {stats && stats.follow_ups_due > 0 && (
        <Alert
          severity="warning"
          icon={<NotificationsActiveIcon />}
          action={
            <Button
              color="inherit"
              size="small"
              onClick={() => {
                setFollowUpsOnly(true);
                setStatuses([]);
                setMatchesOnly(false);
                setPage(0);
              }}
            >
              Show
            </Button>
          }
        >
          {stats.follow_ups_due} follow-up{stats.follow_ups_due === 1 ? "" : "s"} due.
        </Alert>
      )}

      {summary && stats && (
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Paper sx={{ px: 2, py: 1, minWidth: 110 }}>
            <Typography variant="caption" color="text.secondary">
              Total
            </Typography>
            <Typography variant="h6">{stats.total_jobs}</Typography>
          </Paper>
          <Paper sx={{ px: 2, py: 1, minWidth: 110 }}>
            <Typography variant="caption" color="text.secondary">
              Score {stats.min_score}+
            </Typography>
            <Typography variant="h6">{stats.passing}</Typography>
          </Paper>
          {summary.map((item) => {
            const active = statuses.length === 1 && statuses[0] === item.status;
            return (
              <Paper
                key={item.status}
                onClick={() => showOnly(item.status)}
                sx={{
                  px: 2,
                  py: 1,
                  minWidth: 110,
                  cursor: "pointer",
                  outline: active ? 2 : 0,
                  outlineColor: "primary.main",
                  "&:hover": { bgcolor: "action.hover" },
                }}
              >
                <Typography variant="caption" color="text.secondary">
                  {STATUS_LABELS[item.status]}
                </Typography>
                <Typography variant="h6">{item.value}</Typography>
              </Paper>
            );
          })}
        </Stack>
      )}

      <Paper sx={{ p: 2 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ md: "center" }}>
          <FormControl size="small" sx={{ minWidth: 220 }}>
            <InputLabel>Status</InputLabel>
            <Select
              multiple
              value={statuses}
              input={<OutlinedInput label="Status" />}
              onChange={(event) => {
                setStatuses(event.target.value as Status[]);
                setPage(0);
              }}
              displayEmpty
              renderValue={(selectedValues) =>
                (selectedValues as Status[]).map((value) => STATUS_LABELS[value]).join(", ") ||
                "All"
              }
            >
              {STATUSES.map((status) => (
                <MenuItem key={status} value={status}>
                  {STATUS_LABELS[status]}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <TextField
            size="small"
            label="Min score"
            type="number"
            value={minScore}
            onChange={(event) => {
              const value = event.target.value;
              setMinScore(value === "" ? "" : Number(value));
              setPage(0);
            }}
            sx={{ width: 130 }}
            inputProps={{ min: 0, max: 100 }}
          />

          <TextField
            size="small"
            label="Search title, company or text"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(0);
            }}
            sx={{ flexGrow: 1, minWidth: 240 }}
          />

          <FormControlLabel
            control={
              <Switch
                checked={matchesOnly}
                onChange={(event) => {
                  setMatchesOnly(event.target.checked);
                  setPage(0);
                }}
              />
            }
            label={`Matches only (${passMark ?? "…"}+)`}
          />

          <FormControlLabel
            control={
              <Switch
                checked={followUpsOnly}
                onChange={(event) => {
                  setFollowUpsOnly(event.target.checked);
                  setPage(0);
                }}
              />
            }
            label="Follow-ups due"
          />

          <FormControlLabel
            control={
              <Switch
                checked={remoteOnly}
                onChange={(event) => {
                  setRemoteOnly(event.target.checked);
                  setPage(0);
                }}
              />
            }
            label="Remote only"
          />

          <Button
            size="small"
            color="error"
            startIcon={<DeleteSweepIcon />}
            disabled={!stats || stats.total_jobs === 0}
            onClick={() => setClearAllOpen(true)}
          >
            Delete all
          </Button>
        </Stack>
      </Paper>

      {error && <Alert severity="error">{error}</Alert>}

      <Paper>
        {loading && <LinearProgress />}
        <TableContainer>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell sortDirection={sort === "score" ? order : false}>
                  <TableSortLabel
                    active={sort === "score"}
                    direction={order}
                    onClick={() => toggleSort("score")}
                  >
                    Score
                  </TableSortLabel>
                </TableCell>
                <TableCell>Title</TableCell>
                <TableCell sortDirection={sort === "company" ? order : false}>
                  <TableSortLabel
                    active={sort === "company"}
                    direction={order}
                    onClick={() => toggleSort("company")}
                  >
                    Company
                  </TableSortLabel>
                </TableCell>
                <TableCell>Location</TableCell>
                <TableCell>Source</TableCell>
                <TableCell>Language</TableCell>
                <TableCell sortDirection={sort === "first_seen" ? order : false}>
                  <TableSortLabel
                    active={sort === "first_seen"}
                    direction={order}
                    onClick={() => toggleSort("first_seen")}
                  >
                    Seen
                  </TableSortLabel>
                </TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right" sx={{ width: 56 }} />
              </TableRow>
            </TableHead>
            <TableBody>
              {jobs.map((job) => (
                <TableRow
                  key={job.id}
                  hover
                  sx={{ cursor: "pointer" }}
                  onClick={() => setSelected(job.id)}
                >
                  <TableCell sx={{ width: 90 }}>
                    {job.analysis?.score !== null && job.analysis?.score !== undefined ? (
                      <Chip
                        size="small"
                        label={job.analysis.score}
                        color={scoreColor(job.analysis.score, passMark ?? undefined)}
                      />
                    ) : (
                      <Tooltip title={job.analysis?.stage ?? "not analysed"}>
                        <Chip size="small" label="—" variant="outlined" />
                      </Tooltip>
                    )}
                  </TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Typography variant="body2" fontWeight={500}>
                        {job.title}
                      </Typography>
                      {job.remote && <Chip size="small" variant="outlined" label="remote" />}
                    </Stack>
                  </TableCell>
                  <TableCell>{job.company}</TableCell>
                  <TableCell>{job.location}</TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={0.5} alignItems="center">
                      <Tooltip title={job.publisher ? "Found via Google Jobs (JSearch)" : ""}>
                        <Chip size="small" variant="outlined" label={job.publisher || job.source} />
                      </Tooltip>
                      {job.url && (
                        <Tooltip title="Open the original posting">
                          <IconButton
                            size="small"
                            href={job.url}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(event) => event.stopPropagation()}
                          >
                            <OpenInNewIcon fontSize="inherit" />
                          </IconButton>
                        </Tooltip>
                      )}
                    </Stack>
                  </TableCell>
                  <TableCell>
                    {job.analysis?.german_required === true && (
                      <Tooltip title={job.analysis.language_evidence || "German required"}>
                        <Chip size="small" color="error" icon={<LanguageIcon />} label="DE" />
                      </Tooltip>
                    )}
                    {job.analysis?.german_required === false && (
                      <Chip size="small" color="success" variant="outlined" label="EN ok" />
                    )}
                  </TableCell>
                  <TableCell>{new Date(job.first_seen).toLocaleDateString()}</TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={0.5} alignItems="center">
                      <Chip
                        size="small"
                        label={STATUS_LABELS[job.application.status] ?? job.application.status}
                        color={statusColor[job.application.status] ?? "default"}
                      />
                      {job.application.follow_up_date &&
                        (job.application.status === "applied" ||
                          job.application.status === "interested") && (
                          <Tooltip title={`Follow up ${formatDay(job.application.follow_up_date)}`}>
                            <NotificationsActiveIcon
                              fontSize="small"
                              color={isDue(job.application.follow_up_date) ? "warning" : "disabled"}
                            />
                          </Tooltip>
                        )}
                    </Stack>
                  </TableCell>
                  <TableCell align="right">
                    <Tooltip title="Delete this job">
                      <IconButton
                        size="small"
                        onClick={(event) => {
                          event.stopPropagation(); // the row itself opens the drawer
                          setPendingDelete(job);
                        }}
                      >
                        <DeleteIcon fontSize="inherit" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
              {!loading && jobs.length === 0 && (
                <TableRow>
                  <TableCell colSpan={9}>
                    <Box sx={{ py: 4, textAlign: "center" }}>
                      <Typography color="text.secondary">
                        {matchesOnly
                          ? `Nothing scored ${passMark ?? 0} or above yet. Turn off "Matches only" to see everything collected, or press "Run now".`
                          : 'No jobs match these filters. Try "Run now" or widen the status filter.'}
                      </Typography>
                    </Box>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
        <TablePagination
          component="div"
          count={total}
          page={page}
          rowsPerPage={rowsPerPage}
          onPageChange={(_, newPage) => setPage(newPage)}
          onRowsPerPageChange={(event) => {
            setRowsPerPage(Number(event.target.value));
            setPage(0);
          }}
          rowsPerPageOptions={[10, 25, 50, 100]}
        />
      </Paper>

      <JobDrawer
        jobId={selected}
        onClose={() => setSelected(null)}
        onChanged={load}
        llmEnabled={stats?.llm_enabled ?? false}
        passMark={passMark ?? undefined}
      />

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete this job?"
        message={
          pendingDelete
            ? `"${pendingDelete.title}" at ${pendingDelete.company || "an unnamed company"} will be removed ` +
              "along with its score and tracking history. A later run can find it again."
            : ""
        }
        onCancel={() => setPendingDelete(null)}
        onConfirm={async () => {
          if (pendingDelete) await api.deleteJob(pendingDelete.id);
          setPendingDelete(null);
          await load();
        }}
      />

      <ConfirmDialog
        open={clearAllOpen}
        title="Delete every job?"
        message={
          `All ${stats?.total_jobs ?? 0} stored jobs go, including the ones you marked applied or ` +
          "interested, with their scores and tracking history. The run history stays - clear that on the Runs tab."
        }
        confirmLabel="Delete everything"
        onCancel={() => setClearAllOpen(false)}
        onConfirm={async () => {
          await api.deleteAllJobs();
          setClearAllOpen(false);
          setPage(0);
          await load();
        }}
      />

      {loading && jobs.length === 0 && (
        <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
          <CircularProgress />
        </Box>
      )}
    </Stack>
  );
}
