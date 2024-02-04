import { createRoot } from "svelte";
import App from "./components/App.svelte";

export default createRoot(App, { target: document.getElementById("app")! });
