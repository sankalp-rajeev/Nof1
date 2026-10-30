import "@testing-library/jest-dom/vitest";
import { afterEach, beforeAll, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import { createRequire } from "node:module";

// No frontend test may call a live API. Explicitly fail browser and Node transports.
beforeAll(() => {
  const blocked = () => { throw new Error("Network is disabled in tests"); };
  vi.stubGlobal("fetch", blocked);
  vi.stubGlobal("WebSocket", blocked);
  vi.spyOn(XMLHttpRequest.prototype, "open").mockImplementation(blocked);
  const require = createRequire(import.meta.url);
  for (const name of ["node:http", "node:https"]) {
    const transport = require(name) as typeof import("node:http");
    vi.spyOn(transport, "request").mockImplementation(blocked);
    vi.spyOn(transport, "get").mockImplementation(blocked);
  }
  const net = require("node:net") as typeof import("node:net");
  vi.spyOn(net.Socket.prototype, "connect").mockImplementation(blocked);
});

afterEach(cleanup);
