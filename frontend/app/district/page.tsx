import DistrictClient from "./DistrictClient";

// District report. The district comes from ?id= (a static site has no per-district route);
// old /district/<id> links still work through the redirect in vercel.json.
export default function DistrictPage() {
  return <DistrictClient />;
}
