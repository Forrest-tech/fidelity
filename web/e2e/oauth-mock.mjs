// A local OpenID Connect provider for the end-to-end tests (oauth2-mock-server, MIT): the "Company SSO"
// button goes through the real redirect flow (authorize -> code -> token with PKCE -> userinfo) without
// any outside service. A test picks who signs in with  GET /__as?email=...&verified=1  before the click,
// or makes the provider refuse with  GET /__as?deny=1  (the person pressed Cancel).
import http from "node:http";
import { OAuth2Server } from "oauth2-mock-server";

const PORT = Number(process.env.OIDC_MOCK_PORT || 8767);
let who = { email: "reviewer@example.com", verified: true, deny: false };

const server = new OAuth2Server();
await server.issuer.keys.generate("RS256");
server.service.on("beforeUserinfo", (res) => {
  res.body = { sub: `mock-${who.email}`, email: who.email, email_verified: who.verified };
});
server.service.on("beforeAuthorizeRedirect", (authorizeRedirectUri) => {
  if (who.deny) {
    authorizeRedirectUri.url.searchParams.delete("code");
    authorizeRedirectUri.url.searchParams.set("error", "access_denied");
  }
});

const issuerUrl = `http://127.0.0.1:${PORT}`;
server.issuer.url = issuerUrl;
const handler = server.service.requestHandler;
http
  .createServer((req, res) => {
    const u = new URL(req.url, issuerUrl);
    if (u.pathname === "/__as") {
      who = {
        email: u.searchParams.get("email") || who.email,
        verified: u.searchParams.get("verified") !== "0",
        deny: u.searchParams.get("deny") === "1",
      };
      res.writeHead(200, { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" });
      res.end(JSON.stringify(who));
      return;
    }
    if (u.pathname === "/.well-known/openid-configuration") {
      // like a real identity provider, accept a confidential client (client id + secret)
      const body = JSON.stringify({
        issuer: issuerUrl,
        authorization_endpoint: `${issuerUrl}/authorize`,
        token_endpoint: `${issuerUrl}/token`,
        userinfo_endpoint: `${issuerUrl}/userinfo`,
        jwks_uri: `${issuerUrl}/jwks`,
        response_types_supported: ["code"],
        grant_types_supported: ["authorization_code"],
        token_endpoint_auth_methods_supported: ["client_secret_post", "client_secret_basic"],
        code_challenge_methods_supported: ["S256"],
        id_token_signing_alg_values_supported: ["RS256"],
        subject_types_supported: ["public"],
        scopes_supported: ["openid", "email", "profile"],
      });
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(body);
      return;
    }
    if (u.pathname === "/health") {
      res.writeHead(200);
      res.end("ok");
      return;
    }
    handler(req, res);
  })
  .listen(PORT, "127.0.0.1", () => console.log(`OIDC mock on ${issuerUrl}`));
