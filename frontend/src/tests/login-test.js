// src/tests/login-test.ts
import http from "k6/http";
import { check, sleep } from "k6";

var users = [
  { email: "testuser1-1789585577757-1@example.com", password: "pass1@punk" },
  { email: "testuser2-1789585577757-2@example.com", password: "pass2@punk" },
  { email: "testuser3-1789585577757-3@example.com", password: "pass3@punk" },
];

var options = {
  vus: 3,
  iterations: 3
};

function login_test_default() {
  const user = users[(__VU - 1) % users.length];

  const payload = JSON.stringify({
    email: user.email,
    password: user.password
  });

  const params = {
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": "7d95e8a535d8e35e9d62b32cbc542b1a0b958e9b4e634abbfa68610777cc68b1"
    },
    timeout: "30s", // give slow responses a chance instead of erroring immediately
  };

  const res = http.post("http://localhost:8000/auth/login", payload, params);

  // Guard against a dead/empty response before touching res.json()
  if (res.status === 0 || res.body === null) {
    console.error(`VU ${__VU} CONNECTION FAILED | error=${res.error}`);
    sleep(1);
    return;
  }

  let json;
  try {
    json = res.json();
  } catch (e) {
    console.error(`VU ${__VU} FAILED TO PARSE JSON | status=${res.status} | body=${res.body} `, e);
    sleep(1);
    return;
  }

  const ok = check(res, {
    "status is 200": (r) => r.status === 200,
    "has access_token": () => json && json.access_token !== undefined,
    "has refresh_token": () => json && json.refresh_token !== undefined
  });

  if (!ok) {
    console.error(`VU ${__VU} FAILED | status=${res.status} | body=${res.body}`);
  } else {
    console.log(`VU ${__VU} OK | status=${res.status} | email=${user.email}`);
  }

  sleep(1);
}

export {
  login_test_default as default,
  options
};