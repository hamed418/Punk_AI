import Link from "next/link";

export default function Navbar() {
  return (
    <nav className="flex justify-center! gap-[clamp(28px,4vw,56px)] text-[12.5px] uppercase tracking-[1.75px] font-medium">
      {/* <Link
        href="/manifesto"
        className="transition-opacity duration-200 hover:opacity-50"
      >
        Manifesto
      </Link>
      <Link
        href="/team"
        className="transition-opacity duration-200 hover:opacity-50"
      >
        Team
      </Link>
      <Link
        href="/news"
        className="transition-opacity duration-200 hover:opacity-50"
      >
        News
      </Link> */}
      <Link
        href="mailto:will@usepunk.ai"
        className="transition-opacity duration-200 hover:opacity-50"
      >
        Contact a Founder
      </Link>
    </nav>
  );
}



