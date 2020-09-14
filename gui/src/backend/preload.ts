import { contextBridge, ipcRenderer } from "electron";
import { platform } from "process";

contextBridge.exposeInMainWorld("__electronBackend", {
  ipcRenderer: ipcRenderer,
  platform: platform,
});
