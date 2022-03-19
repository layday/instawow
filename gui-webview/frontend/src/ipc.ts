import { Client, RequestManager, WebSocketTransport } from "@open-rpc/client-js";
import { Lock } from "semaphore-async-await";

export type RequestObject = Parameters<Client["request"]>[0];

/**
 * A client wrapper which retrieves the server address from the backend and
 * automatically re-establishes the connection to the server when it drops.
 */
export class RClient {
  private readonly _clientInitialisationLock = new Lock();
  private _transport?: WebSocketTransport;
  private _client?: Client;

  get client(): Promise<Client> {
    return this._clientInitialisationLock.execute(async () => {
      if (
        this._client === undefined ||
        [WebSocket.CLOSING, WebSocket.CLOSED].includes(this._transport!.connection.readyState)
      ) {
        this._transport = new WebSocketTransport(`ws://${location.host}/api`);
        this._client = new Client(new RequestManager([this._transport]));
      }
      return this._client;
    });
  }
}
