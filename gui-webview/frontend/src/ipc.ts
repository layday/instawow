import { Api } from "./api";
import { getClient } from "./client";

export const api = new Api(getClient());
