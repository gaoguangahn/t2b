const path = require("node:path");

module.exports = {
  apps: [
    {
      name: "atestservice-api",
      script: path.join(__dirname, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python"),
      args: "-m atestservice.main --host 0.0.0.0 --port 9091",
      cwd: __dirname,
      watch: false,
      autorestart: true,
      env: {
        PYTHONPATH: path.join(__dirname, "src")
      }
    }
  ]
};
