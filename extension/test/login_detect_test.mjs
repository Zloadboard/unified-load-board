import { isLoginResponse, looksLikeLoginUrl, looksLikeLoginHtml } from "../lib/normalize.js";

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

// URL board paths must NOT look like login
assert(!looksLikeLoginUrl("https://carrier.arrivelogistics.com/find-loads"), "arrive board");
assert(!looksLikeLoginUrl("https://carriers.arcb.com/Shipments"), "arcbest board");
assert(looksLikeLoginUrl("https://login.id.rxo.com/u/login"), "rxo login");
assert(looksLikeLoginUrl("https://foo.auth0.com/u/login"), "auth0");

// SPA HTML with incidental "password" in JS should NOT trip
const spa = "<!doctype html><html><body><script>var password=1; find-loads board</script>Shipments list</body></html>";
assert(!looksLikeLoginHtml(spa, "https://carriers.arcb.com/Shipments"), "spa false positive");

// Strong login HTML
const loginHtml = "<!doctype html><html><body><form action='/login'><input type='password'>Enter your password</form></body></html>";
assert(looksLikeLoginHtml(loginHtml, "https://example.com/login"), "strong login html");

// JSON GraphQL with validation error is NOT login
assert(
  !isLoginResponse(200, "application/json", JSON.stringify({ errors: [{ message: "validation failed" }] }), "https://x/graphql"),
  "gql validation"
);
assert(
  isLoginResponse(200, "application/json", JSON.stringify({ errors: [{ message: "Unauthorized" }] }), "https://x/graphql"),
  "gql unauthorized"
);
assert(isLoginResponse(401, "application/json", "{}", "https://x/api"), "401");

// HTML soft path
assert(
  !isLoginResponse(200, "text/html", spa, "https://carriers.arcb.com/Shipments"),
  "spa html not login"
);

console.log("login_detect_test: all passed");
