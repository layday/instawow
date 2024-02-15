import { createRoot } from "svelte";
import App from "./components/App.svelte";
import { ALERTS_KEY, makeAlerts } from "./stores/alerts.svelte";
import { API_KEY, makeApi } from "./stores/api";
import {
  ACTIVE_PROFILE_KEY,
  PROFILES_KEY,
  makeActiveProfile,
  makeProfiles,
} from "./stores/profiles.svelte";

const defaultContext = {
  [ACTIVE_PROFILE_KEY]: makeActiveProfile(),
  [ALERTS_KEY]: makeAlerts(),
  [API_KEY]: makeApi(),
  [PROFILES_KEY]: makeProfiles(),
};

const context = new Map(Object.entries(defaultContext));

export default createRoot(App, { context, target: document.getElementById("app")! });
