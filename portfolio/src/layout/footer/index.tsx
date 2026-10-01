"use client";

import { Text } from "@mantine/core";

export default function Footer() {
  return (
    <Text
      className="fixed! bottom-6! left-1/2! -translate-x-1/2! z-10! inline-flex! gap-6! text-[10.5px]! uppercase! tracking-[2.3px]! text-(--muted)!"
    >
      <Text className="text-[10.56px]!">NYC</Text>
      <Text className="text-[10.56px]!">Dhaka</Text>
      <Text className="text-[10.56px]!">Montreal</Text>
    </Text>
  );
}
