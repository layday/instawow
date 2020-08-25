import { spawn } from "child_process";
import path from "path";
import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";
import contextMenu from "electron-context-menu";

const sleep = (ms: number) => {
  return new Promise((resolve) => setTimeout(resolve, ms));
};

const getBinPath = () => {
  return path.join(app.getAppPath(), "..", "..", "MacOS");
};

const spawnInstawow = () => {
  if (app.isPackaged) {
    return spawn(path.join(getBinPath(), "instawow"), ["listen"], {
      stdio: [null, null, null, "ipc"],
    });
  } else {
    return spawn("python", ["-m", "instawow", "--debug", "listen"], {
      stdio: [null, null, null, "ipc"],
    });
  }
};

const createWindow = () => {
  // Create the browser window.
  const win = new BrowserWindow({
    width: 800,
    height: 600,
    webPreferences: {
      nodeIntegration: true,
    },
    vibrancy: "titlebar",
    titleBarStyle: "hidden",
    trafficLightPosition: { x: 20, y: 40 },
  });

  // and load the index.html of the app.
  win.loadFile("./build/index.html");

  // Open the DevTools.
  if (!app.isPackaged) {
    win.webContents.openDevTools();
  }
};

const instawow = spawnInstawow();
let serverAddress: string;

instawow.once("message", (message) => (serverAddress = message.address));

instawow.stderr.on("data", (data) => {
  if (data.toString().trim() !== "Aborted!") {
    dialog.showErrorBox("Error", `stderr: ${data}`);
  }
});

ipcMain.handle("get-server-address", async () => {
  while (typeof serverAddress === "undefined") {
    await sleep(50);
  }
  return serverAddress;
});

ipcMain.handle("select-dir", async () => {
  const result = await dialog.showOpenDialog({ properties: ["openDirectory", "createDirectory"] });
  return [result.canceled, result.filePaths];
});

ipcMain.on("reveal-folder", (event, path: string) => shell.showItemInFolder(path));

ipcMain.on("open-url", (event, url: string) => shell.openExternal(url));

// This method will be called when Electron has finished
// initialization and is ready to create browser windows.
// Some APIs can only be used after this event occurs.
app.whenReady().then(createWindow);

// Quit when all windows are closed, except on macOS. There, it's common
// for applications and their menu bar to stay active until the user quits
// explicitly with Cmd + Q.
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("web-contents-created", () => {
  contextMenu();
});

app.on("activate", () => {
  // On macOS it's common to re-create a window in the app when the
  // dock icon is clicked and there are no other windows open.
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

app.on("will-quit", () => {
  instawow.kill("SIGINT");
});
