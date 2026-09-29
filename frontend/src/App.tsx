import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  AppBar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  Snackbar,
  Tab,
  Tabs,
  Toolbar,
  Typography,
} from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { api } from "./api";
import type { Health } from "./types";
import CVPage from "./pages/CVPage";
import JobsPage from "./pages/JobsPage";
import RunsPage from "./pages/RunsPage";
import SettingsPage from "./pages/SettingsPage";
import TrackerPage from "./pages/TrackerPage";

const TABS = [
  { label: "Jobs", path: "/jobs" },
  { label: "Tracker", path: "/tracker" },
  { label: "Runs", path: "/runs" },
  { label: "CV", path: "/cv" },
  { label: "Settings", path: "/settings" },
];

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const [health, setHealth] = useState<Health | null>(null);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<{ text: string; severity: "success" | "error" | "info" } | null>(
    null,
  );
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  const pollRun = useCallback(() => {
    const timer = setInterval(async () => {
      try {
        const { active } = await api.runActive();
        if (!active) {
          clearInterval(timer);
          setRunning(false);
          setMessage({ text: "Run finished.", severity: "success" });
          setRefreshKey((key) => key + 1);
        }
      } catch {
        clearInterval(timer);
        setRunning(false);
      }
    }, 3000);
    return timer;
  }, []);

  useEffect(() => {
    // A run may already be going when the dashboard loads (scheduler, catch-up).
    api.runActive().then(({ active }) => {
      if (active) {
        setRunning(true);
        pollRun();
      }
    });
  }, [pollRun]);

  const startRun = async () => {
    try {
      await api.triggerRun();
      setRunning(true);
      setMessage({ text: "Run started. This can take a few minutes.", severity: "info" });
      pollRun();
    } catch (error) {
      setMessage({ text: (error as Error).message, severity: "error" });
    }
  };

  const activeTab = TABS.findIndex((tab) => location.pathname.startsWith(tab.path));

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
      <AppBar position="static" color="default" elevation={1}>
        <Toolbar sx={{ gap: 2 }}>
          <Typography variant="h6" sx={{ fontWeight: 700 }}>
            Job Portal
          </Typography>
          <Tabs
            value={activeTab === -1 ? 0 : activeTab}
            onChange={(_, index) => navigate(TABS[index].path)}
            sx={{ flexGrow: 1 }}
          >
            {TABS.map((tab) => (
              <Tab key={tab.path} label={tab.label} />
            ))}
          </Tabs>

          {health && !health.llm_enabled && (
            <Chip size="small" color="warning" label="No OpenAI key" title="Scoring is off" />
          )}
          {health?.next_run && (
            <Chip
              size="small"
              variant="outlined"
              label={`Next run ${new Date(health.next_run).toLocaleString()}`}
            />
          )}
          <Button
            variant="contained"
            startIcon={running ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
            onClick={startRun}
            disabled={running}
          >
            {running ? "Running" : "Run now"}
          </Button>
        </Toolbar>
      </AppBar>

      <Container maxWidth="xl" sx={{ py: 3 }}>
        <Routes>
          <Route path="/" element={<Navigate to="/jobs" replace />} />
          <Route path="/jobs" element={<JobsPage refreshKey={refreshKey} />} />
          <Route path="/tracker" element={<TrackerPage refreshKey={refreshKey} />} />
          <Route path="/runs" element={<RunsPage refreshKey={refreshKey} />} />
          <Route path="/cv" element={<CVPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/jobs" replace />} />
        </Routes>
      </Container>

      <Snackbar
        open={Boolean(message)}
        autoHideDuration={5000}
        onClose={() => setMessage(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      >
        <Alert severity={message?.severity ?? "info"} onClose={() => setMessage(null)}>
          {message?.text}
        </Alert>
      </Snackbar>
    </Box>
  );
}
