import { spawn } from "child_process";
import path from "path";
import { app, BrowserWindow, dialog, ipcMain, Menu, shell } from "electron";
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
      // contextIsolation: true,    // to investigate
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

// Construct a menu from `actions` and wait for it to be dismissed.
// Returns the `action` value of the item that was selected if any.
const waitForMenuSelection = async (
  actions: { action: string; label: string }[]
): Promise<string> => {
  let selectedAction: string;

  const menu = Menu.buildFromTemplate(
    actions.map(({ action, label }) => ({
      id: action,
      label: label,
      click: () => (selectedAction = action),
    }))
  );

  const getSelection = (): Promise<string> =>
    new Promise((resolve) => {
      menu.popup({ callback: () => resolve(selectedAction) });
    });

  return await getSelection();
};

const instawow = spawnInstawow();
let serverAddress: string;

instawow.once("message", (message: any) => (serverAddress = message.address));

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

ipcMain.handle("select-folder", async (event, defaultPath?: string) => {
  const result = await dialog.showOpenDialog({
    defaultPath: defaultPath,
    properties: ["openDirectory", "createDirectory"],
  });
  return [result.canceled, result.filePaths];
});

ipcMain.handle(
  "get-action-from-context-menu",
  async (event, actions: { action: string; label: string }[]) => {
    return await waitForMenuSelection(actions);
  }
);

ipcMain.on("reveal-folder", (event, pathComponents: string[]) =>
  shell.showItemInFolder(path.join(...pathComponents))
);

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
