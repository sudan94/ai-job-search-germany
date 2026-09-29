import { useEffect, useRef, useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";

import { api } from "../api";
import type { CVProfile } from "../types";

type Entry = Record<string, unknown>;

const str = (value: unknown) => (typeof value === "string" ? value : "");

/** One parsed entry (a job, degree or project) as a header line plus details. */
function EntryList({ title, items, header, body }: {
  title: string;
  items: Entry[];
  header: (item: Entry) => string;
  body: (item: Entry) => string[];
}) {
  if (items.length === 0) return null;
  return (
    <Box sx={{ mb: 2 }}>
      <Typography variant="subtitle2" gutterBottom>
        {title} ({items.length})
      </Typography>
      <Stack spacing={1}>
        {items.map((item, index) => (
          <Box key={index} sx={{ pl: 1.5, borderLeft: 2, borderColor: "divider" }}>
            <Typography variant="body2" fontWeight={500}>
              {header(item)}
            </Typography>
            {body(item).map((line, lineIndex) => (
              <Typography key={lineIndex} variant="body2" color="text.secondary">
                {line}
              </Typography>
            ))}
          </Box>
        ))}
      </Stack>
    </Box>
  );
}

export default function CVPage() {
  const [profile, setProfile] = useState<CVProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState("");
  const [message, setMessage] = useState<{
    text: string;
    severity: "success" | "warning" | "error";
  } | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);
  const [rawText, setRawText] = useState<string | null>(null);

  const loadRaw = () => {
    api
      .cvRaw()
      .then((raw) => setRawText(raw.text))
      .catch(() => setRawText(""));
  };

  useEffect(() => {
    api
      .cv()
      .then(setProfile)
      .catch(() => setProfile(null))
      .finally(() => setLoading(false));
  }, []);

  const handle = async (action: () => Promise<CVProfile>) => {
    setBusy(true);
    setMessage(null);
    setWarnings([]);
    try {
      const saved = await action();
      setProfile(saved);
      setRawText(null);
      setText("");
      // A CV is always stored, even when the model or the embedding failed.
      // Saying "parsed and stored" over a heuristic fallback would be a lie.
      setWarnings(saved.warnings ?? []);
      setMessage(
        saved.warnings?.length
          ? { text: "CV stored, but some steps did not run.", severity: "warning" }
          : { text: "CV parsed and stored.", severity: "success" },
      );
    } catch (error) {
      setMessage({ text: (error as Error).message, severity: "error" });
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Stack spacing={2}>
      {message && <Alert severity={message.severity}>{message.text}</Alert>}
      {warnings.map((warning) => (
        <Alert key={warning} severity="warning">
          {warning}
        </Alert>
      ))}

      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" gutterBottom>
          Upload a CV
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          PDF, TXT or Markdown. It is parsed once into a structured profile and embedded, then reused
          for every score and letter. Uploading again replaces the active profile.
        </Typography>

        <Stack direction="row" spacing={2} alignItems="center">
          <input
            ref={fileInput}
            type="file"
            accept=".pdf,.txt,.md,.markdown"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) handle(() => api.uploadCV(file));
              event.target.value = "";
            }}
          />
          <Button
            variant="contained"
            startIcon={busy ? <CircularProgress size={16} color="inherit" /> : <UploadFileIcon />}
            onClick={() => fileInput.current?.click()}
            disabled={busy}
          >
            Choose file
          </Button>
        </Stack>

        <Typography variant="subtitle2" sx={{ mt: 3, mb: 1 }}>
          Or paste the text
        </Typography>
        <TextField
          multiline
          minRows={5}
          fullWidth
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="Paste your CV here (at least 100 characters)."
        />
        <Button
          sx={{ mt: 1 }}
          disabled={text.trim().length < 100 || busy}
          onClick={() => handle(() => api.uploadCVText(text))}
        >
          Save pasted CV
        </Button>
      </Paper>

      {profile ? (
        <Paper sx={{ p: 3 }}>
          <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
            <Typography variant="h6" sx={{ flexGrow: 1 }}>
              Active profile: {profile.filename}
            </Typography>
            <Chip
              size="small"
              color={profile.has_embedding ? "success" : "warning"}
              label={profile.has_embedding ? `embedded (${profile.embedding_model})` : "no embedding"}
            />
          </Stack>

          {!profile.has_embedding && (
            <Alert severity="warning" sx={{ mb: 2 }}>
              Without an embedding the similarity prefilter cannot rank this CV against jobs. Upload
              the CV again to rebuild it.
            </Alert>
          )}

          <Alert severity="info" icon={false} sx={{ mb: 2 }}>
            Read {profile.text_chars.toLocaleString()} characters
            {profile.page_count ? ` from ${profile.page_count} page${profile.page_count === 1 ? "" : "s"}` : ""}.
            If a section is missing below, open the extracted text at the bottom: if it is not
            there either, the PDF has that part as an image, so paste the text instead.
          </Alert>

          <Typography variant="subtitle2">Summary</Typography>
          <Typography variant="body2" sx={{ mb: 2 }}>
            {profile.summary || "—"}
          </Typography>

          <Typography variant="subtitle2">
            Years of experience: {profile.years_experience ?? "not stated"}
          </Typography>

          <Typography variant="subtitle2" sx={{ mt: 2 }}>
            Target roles
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
            {profile.role_targets.map((role) => (
              <Chip key={role} size="small" label={role} />
            ))}
          </Stack>

          <Typography variant="subtitle2">Skills</Typography>
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
            {profile.skills.map((skill) => (
              <Chip key={skill} size="small" variant="outlined" label={skill} />
            ))}
          </Stack>

          {profile.languages.length > 0 && (
            <>
              <Typography variant="subtitle2">Languages</Typography>
              <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
                {profile.languages.map((language) => (
                  <Chip key={language} size="small" variant="outlined" label={language} />
                ))}
              </Stack>
            </>
          )}

          <EntryList
            title="Experience"
            items={profile.experience}
            header={(item) =>
              [str(item.title), str(item.company), str(item.period)].filter(Boolean).join(" · ")
            }
            body={(item) =>
              (Array.isArray(item.highlights) ? item.highlights : []).map((line) => `• ${line}`)
            }
          />
          <EntryList
            title="Education"
            items={profile.education ?? []}
            header={(item) =>
              [str(item.degree), str(item.institution), str(item.period)].filter(Boolean).join(" · ")
            }
            body={(item) => (str(item.details) ? [str(item.details)] : [])}
          />
          <EntryList
            title="Projects"
            items={profile.projects ?? []}
            header={(item) => str(item.name)}
            body={(item) =>
              [
                str(item.description),
                Array.isArray(item.technologies) && item.technologies.length
                  ? `Tech: ${item.technologies.join(", ")}`
                  : "",
              ].filter(Boolean)
            }
          />
          {(profile.certifications ?? []).length > 0 && (
            <Box sx={{ mb: 2 }}>
              <Typography variant="subtitle2">Certifications</Typography>
              <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                {profile.certifications.map((item) => (
                  <Chip key={item} size="small" variant="outlined" label={item} />
                ))}
              </Stack>
            </Box>
          )}

          <Accordion
            disableGutters
            variant="outlined"
            onChange={(_, expanded) => {
              if (expanded && rawText === null) loadRaw();
            }}
          >
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="subtitle2">Extracted text (what the parser saw)</Typography>
            </AccordionSummary>
            <AccordionDetails>
              {rawText === null ? (
                <CircularProgress size={20} />
              ) : (
                <Typography
                  variant="body2"
                  component="pre"
                  sx={{
                    whiteSpace: "pre-wrap",
                    fontFamily: "inherit",
                    maxHeight: 500,
                    overflow: "auto",
                    m: 0,
                  }}
                >
                  {rawText || "No text stored."}
                </Typography>
              )}
            </AccordionDetails>
          </Accordion>
        </Paper>
      ) : (
        <Alert severity="info">No CV stored yet. Nothing can be scored until one is uploaded.</Alert>
      )}
    </Stack>
  );
}
