import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  FormControlLabel,
  IconButton,
  Paper,
  Slider,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import AddIcon from "@mui/icons-material/Add";

import { api } from "../api";
import type { Settings, SourceInfo } from "../types";

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6">{title}</Typography>
      {hint && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {hint}
        </Typography>
      )}
      <Box sx={{ mt: hint ? 0 : 2 }}>{children}</Box>
    </Paper>
  );
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [sources, setSources] = useState<SourceInfo[]>([]);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ text: string; severity: "success" | "error" } | null>(null);
  const [newCompany, setNewCompany] = useState({ ats: "greenhouse", slug: "", label: "" });

  useEffect(() => {
    Promise.all([api.settings(), api.sources()])
      .then(([loadedSettings, loadedSources]) => {
        setSettings(loadedSettings);
        setSources(loadedSources);
      })
      .catch((error) => setMessage({ text: (error as Error).message, severity: "error" }));
  }, []);

  const update = <K extends keyof Settings>(key: K, value: Settings[K]) =>
    setSettings((current) => (current ? { ...current, [key]: value } : current));

  const save = async () => {
    if (!settings) return;
    setSaving(true);
    setMessage(null);
    try {
      const saved = await api.saveSettings(settings);
      setSettings(saved);
      setSources(await api.sources());
      setMessage({ text: "Settings saved.", severity: "success" });
    } catch (error) {
      setMessage({ text: (error as Error).message, severity: "error" });
    } finally {
      setSaving(false);
    }
  };

  if (!settings) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Stack spacing={2} sx={{ pb: 6 }}>
      {message && <Alert severity={message.severity}>{message.text}</Alert>}

      <Section
        title="Filtering"
        hint="What survives the pipeline. Rejected jobs stay in the database with their reasons."
      >
        <Stack spacing={3}>
          <FormControlLabel
            control={
              <Switch
                checked={settings.english_only}
                onChange={(event) => update("english_only", event.target.checked)}
              />
            }
            label="English only (drop jobs that require German)"
          />
          <FormControlLabel
            control={
              <Switch
                checked={settings.germany_only}
                onChange={(event) => update("germany_only", event.target.checked)}
              />
            }
            label="Germany only (Germany-based roles, plus remote roles at German employers)"
          />
          <Box>
            <Typography gutterBottom>Minimum score (pass mark): {settings.min_score}</Typography>
            <Stack direction="row" spacing={2} alignItems="center">
              <Slider
                value={settings.min_score}
                min={0}
                max={100}
                step={1}
                marks={[
                  { value: 0, label: "0" },
                  { value: 50, label: "50" },
                  { value: 100, label: "100" },
                ]}
                onChange={(_, value) => update("min_score", value as number)}
              />
              <TextField
                type="number"
                size="small"
                value={settings.min_score}
                onChange={(event) =>
                  update("min_score", Math.max(0, Math.min(100, Number(event.target.value) || 0)))
                }
                inputProps={{ min: 0, max: 100 }}
                sx={{ width: 90 }}
              />
            </Stack>
            <Typography variant="caption" color="text.secondary">
              A scored job at or above this is a match. Saving a new value re-sorts the jobs
              already scored, not only future ones. Jobs you have marked yourself are never moved.
            </Typography>
          </Box>
          <FormControlLabel
            control={
              <Switch
                checked={settings.auto_reject_below_min_score}
                onChange={(event) => update("auto_reject_below_min_score", event.target.checked)}
              />
            }
            label={`Mark jobs scored below ${settings.min_score} as "Rejected by system"`}
          />
          <FormControlLabel
            control={
              <Switch
                checked={settings.jobs_matches_only_default}
                onChange={(event) => update("jobs_matches_only_default", event.target.checked)}
              />
            }
            label={`Open the Jobs page on matches only (${settings.min_score}+)`}
          />
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
            <TextField
              label="Matches wanted per run"
              type="number"
              size="small"
              fullWidth
              value={settings.target_matches_per_run}
              onChange={(event) => update("target_matches_per_run", Number(event.target.value))}
              helperText="A run scores best-match-first and stops once it has this many above the threshold. 0 means no target."
            />
            <TextField
              label="Max scored jobs per run"
              type="number"
              size="small"
              fullWidth
              value={settings.max_llm_scores_per_run}
              onChange={(event) => update("max_llm_scores_per_run", Number(event.target.value))}
              helperText="Hard ceiling on scoring calls, whether or not the target was reached."
            />
          </Stack>
          <Box>
            <Typography gutterBottom>
              Similarity floor:{" "}
              {settings.similarity_floor === 0 ? "off" : settings.similarity_floor.toFixed(2)}
            </Typography>
            <Slider
              value={settings.similarity_floor}
              min={0}
              max={0.8}
              step={0.01}
              onChange={(_, value) => update("similarity_floor", value as number)}
            />
            <Typography variant="caption" color="text.secondary">
              Optional hard cut below which no model call is made. Leave at 0 unless you have
              looked at the similarity range on the Runs page: the useful value differs between
              the OpenAI and built-in lexical backends.
            </Typography>
          </Box>
        </Stack>
      </Section>

      <Section
        title="Title filter"
        hint="Runs on the title before anything is billed. This is what keeps hardware, sales and senior roles out of the list. Excluded terms win over included ones."
      >
        <Stack spacing={2}>
          <FormControlLabel
            control={
              <Switch
                checked={settings.relevance_filter}
                onChange={(event) => update("relevance_filter", event.target.checked)}
              />
            }
            label="Filter by job title"
          />
          <TextField
            label="Drop titles containing (comma separated)"
            fullWidth
            multiline
            disabled={!settings.relevance_filter}
            value={settings.exclude_title_terms.join(", ")}
            onChange={(event) =>
              update(
                "exclude_title_terms",
                event.target.value.split(",").map((value) => value.trim()),
              )
            }
            helperText="Seniority, disciplines and stacks that are not yours. Terms of 5+ characters match inside words so German compounds are caught; shorter ones must be whole words, which is what stops 'java' firing on 'JavaScript'."
          />
          <TextField
            label="Keep only titles containing (comma separated)"
            fullWidth
            multiline
            disabled={!settings.relevance_filter}
            value={settings.include_title_terms.join(", ")}
            onChange={(event) =>
              update(
                "include_title_terms",
                event.target.value.split(",").map((value) => value.trim()),
              )
            }
            helperText="At least one must appear. Leave empty to keep everything that was not excluded."
          />
        </Stack>
      </Section>

      <Section title="Search" hint="Applied to every source that supports keywords and locations.">
        <Stack spacing={2}>
          <TextField
            label="Keywords (comma separated)"
            fullWidth
            multiline
            value={settings.keywords.join(", ")}
            onChange={(event) =>
              update(
                "keywords",
                event.target.value.split(",").map((value) => value.trim()),
              )
            }
            helperText="Include German titles too: the Bundesagentur index is mostly German."
          />
          <TextField
            label="Locations (comma separated)"
            fullWidth
            value={settings.locations.join(", ")}
            onChange={(event) =>
              update(
                "locations",
                event.target.value.split(",").map((value) => value.trim()),
              )
            }
          />
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
            <TextField
              label="Radius (km)"
              type="number"
              size="small"
              value={settings.radius_km}
              onChange={(event) => update("radius_km", Number(event.target.value))}
            />
            <TextField
              label="Max age (days)"
              type="number"
              size="small"
              value={settings.max_age_days}
              onChange={(event) => update("max_age_days", Number(event.target.value))}
            />
            <TextField
              label="Results per source"
              type="number"
              size="small"
              value={settings.results_per_source}
              onChange={(event) => update("results_per_source", Number(event.target.value))}
            />
            <FormControlLabel
              control={
                <Switch
                  checked={settings.remote_only}
                  onChange={(event) => update("remote_only", event.target.checked)}
                />
              }
              label="Remote only"
            />
          </Stack>
        </Stack>
      </Section>

      <Section title="Sources">
        <Stack spacing={1}>
          {sources.map((source) => (
            <Stack key={source.name} direction="row" alignItems="center" spacing={1}>
              <FormControlLabel
                sx={{ flexGrow: 1 }}
                control={
                  <Switch
                    checked={Boolean(settings.sources[source.name])}
                    onChange={(event) =>
                      update("sources", { ...settings.sources, [source.name]: event.target.checked })
                    }
                  />
                }
                label={source.label}
              />
              {source.requires_config && !source.configured && (
                <Chip
                  size="small"
                  color="warning"
                  label={
                    source.name === "adzuna"
                      ? "needs ADZUNA keys in .env"
                      : source.name === "jsearch"
                        ? "needs JSEARCH_API_KEY in .env"
                        : "needs companies below"
                  }
                />
              )}
            </Stack>
          ))}
        </Stack>
      </Section>

      <Section
        title="Indeed, StepStone & more (JSearch)"
        hint="Indeed and StepStone have no public API and block scrapers. Their postings are indexed by Google for Jobs, which JSearch exposes. Free RapidAPI key: 200 requests a month."
      >
        <Stack spacing={2}>
          <TextField
            label="Keep only these publishers (comma separated)"
            fullWidth
            value={settings.jsearch_publishers.join(", ")}
            onChange={(event) =>
              update(
                "jsearch_publishers",
                event.target.value.split(",").map((value) => value.trim()),
              )
            }
            helperText="Matched against the board each result came from. Leave empty to keep every publisher."
          />
          <TextField
            label="Max requests per run"
            type="number"
            size="small"
            sx={{ maxWidth: 240 }}
            value={settings.jsearch_max_requests}
            onChange={(event) => update("jsearch_max_requests", Number(event.target.value))}
            helperText="One request per keyword, up to 10 results each. 5 a day stays inside the free tier."
          />
        </Stack>
      </Section>

      <Section
        title="Tracked ATS companies"
        hint="Public Greenhouse, Lever and Ashby boards. The slug is the name in the careers URL."
      >
        <Stack spacing={1}>
          {settings.ats_companies.map((company, index) => (
            <Stack key={`${company.ats}-${company.slug}`} direction="row" spacing={1} alignItems="center">
              <Switch
                checked={company.active}
                onChange={(event) => {
                  const next = [...settings.ats_companies];
                  next[index] = { ...company, active: event.target.checked };
                  update("ats_companies", next);
                }}
              />
              <Chip size="small" label={company.ats} />
              <Typography sx={{ flexGrow: 1 }}>
                {company.label || company.slug}{" "}
                <Typography component="span" variant="caption" color="text.secondary">
                  ({company.slug})
                </Typography>
              </Typography>
              <IconButton
                size="small"
                onClick={() =>
                  update(
                    "ats_companies",
                    settings.ats_companies.filter((_, position) => position !== index),
                  )
                }
              >
                <DeleteIcon fontSize="small" />
              </IconButton>
            </Stack>
          ))}

          <Divider sx={{ my: 1 }} />

          <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
            <TextField
              select
              size="small"
              label="ATS"
              SelectProps={{ native: true }}
              value={newCompany.ats}
              onChange={(event) => setNewCompany({ ...newCompany, ats: event.target.value })}
              sx={{ minWidth: 140 }}
            >
              <option value="greenhouse">greenhouse</option>
              <option value="lever">lever</option>
              <option value="ashby">ashby</option>
            </TextField>
            <TextField
              size="small"
              label="Board slug"
              value={newCompany.slug}
              onChange={(event) => setNewCompany({ ...newCompany, slug: event.target.value })}
            />
            <TextField
              size="small"
              label="Label"
              value={newCompany.label}
              onChange={(event) => setNewCompany({ ...newCompany, label: event.target.value })}
            />
            <Button
              startIcon={<AddIcon />}
              disabled={!newCompany.slug.trim()}
              onClick={() => {
                update("ats_companies", [
                  ...settings.ats_companies,
                  {
                    ats: newCompany.ats,
                    slug: newCompany.slug.trim(),
                    label: newCompany.label.trim() || newCompany.slug.trim(),
                    active: true,
                  },
                ]);
                setNewCompany({ ats: newCompany.ats, slug: "", label: "" });
              }}
            >
              Add
            </Button>
          </Stack>
        </Stack>
      </Section>

      <Section
        title="Daily run"
        hint="The in-process timer only fires while the backend is running. On a laptop, use Task Scheduler or cron with the CLI instead."
      >
        <Stack direction="row" spacing={2} alignItems="center">
          <TextField
            label="Run time (Europe/Berlin)"
            type="time"
            size="small"
            value={settings.daily_run_time}
            onChange={(event) => update("daily_run_time", event.target.value)}
            InputLabelProps={{ shrink: true }}
          />
          <FormControlLabel
            control={
              <Switch
                checked={settings.scheduler_enabled}
                onChange={(event) => update("scheduler_enabled", event.target.checked)}
              />
            }
            label="Scheduler enabled"
          />
        </Stack>
      </Section>

      <Box>
        <Button variant="contained" size="large" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save settings"}
        </Button>
      </Box>
    </Stack>
  );
}
