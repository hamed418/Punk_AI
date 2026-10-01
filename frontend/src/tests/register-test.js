// src/tests/register-test.ts
import http from "k6/http";
import { check, sleep } from "k6";

var users = [
  {
    email: "testuser@example.com",
    password: "pass1@punk",
    full_name: "Test User 1",
    business_name: "Test Business 1",
    business_type: "E-Commerce",
    why_choose_punk: "AI ad optimization"
  }
];

var options = {
  vus: 3,
  // 5 virtual users
  iterations: 3
  // each runs once (1 registration each)
};

function register_test_default() {
  const user = users[(__VU - 1) % users.length];

  // Make email unique per run so re-running the script doesn't hit
  // "email already exists" errors from the previous run
  const uniqueEmail = `${user.email.split("@")[0]}-${Date.now()}-${__VU}@example.com`;

  const payload = JSON.stringify({
    email: uniqueEmail,
    password: user.password,
    full_name: user.full_name,
    business_name: user.business_name,
    business_type: user.business_type,
    why_choose_punk: user.why_choose_punk
  });

  const params = {
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": "7d95e8a535d8e35e9d62b32cbc542b1a0b958e9b4e634abbfa68610777cc68b1"
    }
  };

  const res = http.post("http://localhost:8000/auth/register", payload, params);

  const ok = check(res, {
    "status is 200 or 201": (r) => r.status === 200 || r.status === 201,
  });

  if (!ok) {
    console.error(`VU ${__VU} FAILED | status=${res.status} | body=${res.body}`);
  } else {
    console.log(`VU ${__VU} OK | status=${res.status} | email=${uniqueEmail}`);
  }

  sleep(1);
}

export {
  register_test_default as default,
  options
};