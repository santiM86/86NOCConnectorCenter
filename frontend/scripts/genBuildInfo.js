/* Genera src/buildInfo.json con commit git + timestamp di build.
   Baked nel bundle: se la produzione non ricompila il frontend, il badge
   in UI resta "vecchio" e si capisce subito che la build e' stantia.
   Resiliente: non deve MAI far fallire start/build. */
const { execSync } = require("child_process");
const fs = require("fs");
const path = require("path");

function safe(cmd) {
  try {
    return execSync(cmd, { cwd: path.join(__dirname, ".."), stdio: ["ignore", "pipe", "ignore"] })
      .toString()
      .trim();
  } catch {
    return "";
  }
}

const commit = safe("git rev-parse --short HEAD") || "dev";
const out = { commit, builtAt: new Date().toISOString() };

try {
  fs.writeFileSync(
    path.join(__dirname, "..", "src", "buildInfo.json"),
    JSON.stringify(out, null, 2) + "\n"
  );
  console.log("[buildInfo]", JSON.stringify(out));
} catch (e) {
  console.log("[buildInfo] write skipped:", e.message);
}
