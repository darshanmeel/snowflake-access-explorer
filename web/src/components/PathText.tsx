// Every Path column draws the same strip (PathStrip): one line of node-styled chips, click for the diagram.
import { PathStrip, type PathStripProps } from "./PathStrip";

export const PathText = (p: PathStripProps) => <PathStrip {...p} />;
