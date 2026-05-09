"use client";

import { useState } from "react";

import { Chat } from "@/components/chat";
import { Sidebar } from "@/components/sidebar";

export default function Page() {
  // Bumping this key remounts <Chat>, which reconnects the WS and clears history.
  const [chatKey, setChatKey] = useState(0);

  return (
    <main className="flex h-screen w-screen overflow-hidden">
      <Sidebar onNewChat={() => setChatKey((k) => k + 1)} />
      <section className="flex-1 overflow-hidden">
        <Chat key={chatKey} />
      </section>
    </main>
  );
}
