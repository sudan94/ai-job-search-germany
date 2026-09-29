import { createTheme } from "@mui/material/styles";

export const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#1f4e79" },
    secondary: { main: "#b25b00" },
    background: { default: "#f4f6f8", paper: "#ffffff" },
    success: { main: "#2e7d32" },
    warning: { main: "#ed6c02" },
  },
  typography: {
    fontFamily: '"Inter", "Segoe UI", system-ui, -apple-system, sans-serif',
    h5: { fontWeight: 600 },
    h6: { fontWeight: 600 },
  },
  shape: { borderRadius: 8 },
  components: {
    MuiTableCell: { styleOverrides: { root: { paddingTop: 10, paddingBottom: 10 } } },
    MuiButton: { defaultProps: { disableElevation: true } },
  },
});

/**
 * Score colour is the fastest signal in the table, so keep the bands obvious.
 * The bands follow the configured pass mark: below it is red, from it up to
 * 15 points above is amber, and anything higher is green.
 */
export function scoreColor(
  score: number | null | undefined,
  passMark = 65,
): "success" | "warning" | "error" | "default" {
  if (score === null || score === undefined) return "default";
  if (score >= Math.min(100, passMark + 15)) return "success";
  if (score >= passMark) return "warning";
  return "error";
}

export const statusColor: Record<
  string,
  "default" | "primary" | "secondary" | "success" | "error" | "info" | "warning"
> = {
  new: "info",
  applied: "success",
  system_rejected: "default",
  rejected: "error",
  interested: "primary",
  ignored: "default",
};
