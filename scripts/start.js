const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const root = path.resolve(__dirname, "..");
const backendDir = path.join(root, "backend");

let uvicornCmd = "uvicorn";
const winVenvUvicorn = path.join(root, ".venv", "Scripts", "uvicorn.exe");
const unixVenvUvicorn = path.join(root, ".venv", "bin", "uvicorn");

if (fs.existsSync(winVenvUvicorn)) {
  uvicornCmd = winVenvUvicorn;
} else if (fs.existsSync(unixVenvUvicorn)) {
  uvicornCmd = unixVenvUvicorn;
}

console.log(`Starting PropVerify backend: ${uvicornCmd} app:app --port 8000 --reload`);
const child = spawn(uvicornCmd, ["app:app", "--port", "8000", "--reload"], {
  cwd: backendDir,
  stdio: "inherit",
});

child.on("exit", (code) => {
  process.exit(code || 0);
});
