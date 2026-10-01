"use client";

import Link from "next/link";
import { Text, Menu } from "@mantine/core";
import { AnimatePresence, motion } from "framer-motion";

export default function PortfolioSection() {
  return (
    <div className="flex flex-col items-center gap-8 mt-10" id="portfolio">
      <Menu shadow="none" width="auto" position="bottom" offset={8}>
        <Menu.Target>
          <button
            className="group text-[9.92px]! uppercase! tracking-[3.2px]! text-(--muted)! hover:text-(--fg)! inline-flex! items-center! gap-3! bg-transparent! border-0! font-inherit! cursor-pointer! py-1.5! px-1! transition-colors! duration-250! before:content-['']! before:w-7! before:h-px! before:bg-(--dim)! hover:before:bg-(--fg)! before:transition-all! before:duration-350! after:content-['']! after:w-7! after:h-px! after:bg-(--dim)! hover:after:bg-(--fg)! after:transition-all! after:duration-350!"
            type="button"
          >
            Portfolio
          </button>
        </Menu.Target>
        <Menu.Dropdown
          p={0}
          className="bg-transparent! border-0! shadow-none! overflow-visible! min-w-max!"
        >
          <AnimatePresence mode="wait">
            <motion.div
              initial={{ opacity: 0, height: 0, y: -8 }}
              animate={{ opacity: 1, height: "auto", y: 0 }}
              exit={{ opacity: 0, height: 0, y: -8 }}
              transition={{
                duration: 0.35,
                ease: [0.16, 1, 0.3, 1],
              }}
              className="flex justify-center gap-[clamp(64px,10vw,144px)] mt-1 overflow-hidden"
            >
              <Link
                href="https://usepunk.ai/"
                target="_blank"
                rel="noopener noreferrer"
                className="group inline-flex flex-col items-center gap-2.5 text-base uppercase tracking-[3.5px] font-semibold transition-opacity duration-200 hover:opacity-50"
              >
                <Text className="relative! font-semibold! pb-1! after:content-['']! after:absolute! after:left-1/2! after:right-1/2! after:bottom-0! after:h-px! after:bg-(--fg)! group-hover:after:left-0! group-hover:after:right-0! after:transition-all! after:duration-450!">
                  Punk
                </Text>
                <Text className="text-[9.92px]! tracking-[2.4px]! text-(--muted)! font-medium!">
                  Artificial Intelligence
                </Text>
              </Link>
            </motion.div>
          </AnimatePresence>
        </Menu.Dropdown>
      </Menu>
    </div>
  );
}