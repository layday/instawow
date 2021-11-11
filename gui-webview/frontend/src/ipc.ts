import { RequestManager, Client, WebSocketTransport } from "@open-rpc/client-js";
import { Lock } from "semaphore-async-await";

/**
 * A client wrapper which retrieves the server address from the backend and
 * automatically re-establishes the connection to the server when it drops.
 */
export class RClient {
  private clientInitialisationLock = new Lock();
  private transport?: WebSocketTransport;
  private _client?: Client;

  get client(): Promise<Client> {
    return this.clientInitialisationLock.execute(async () => {
      if (
        this._client === undefined ||
        [WebSocket.CLOSING, WebSocket.CLOSED].includes(this.transport!.connection.readyState)
      ) {
        this.transport = new WebSocketTransport(`ws://${location.host}/api`);
        this._client = new Client(new RequestManager([this.transport]));
      }
      return this._client;
    });
  }
}
