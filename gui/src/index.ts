import { Api } from "./api";
import { getClient } from "./client";
import App from "./components/App.svelte";

export default new App({ props: { api: new Api(getClient()) }, target: document.body });
