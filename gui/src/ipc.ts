import type { ipcRenderer as __ipcRenderer } from "electron";
import type { platform } from "process";

export const backend = (window as typeof window & {
  __electronBackend: {
    ipcRenderer: typeof __ipcRenderer;
    platform: typeof platform;
  };
}).__electronBackend;
export const { ipcRenderer } = backend;
