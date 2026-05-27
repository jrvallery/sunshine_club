#!/usr/bin/env node
import { spawn } from "node:child_process";
import process from "node:process";

const route = process.argv[2] || "/";
const args = [new URL("./review.mjs", import.meta.url).pathname, "--route", route, "--no-fail"];
const child = spawn(process.execPath, args, { stdio: "inherit", cwd: process.cwd() });
child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code || 0);
});
