# Item grading — V7

Item grades explain the current dimension calculation; they do not create a second scoring system.

For a locator, the displayed grade is:

\[
G_j=100\min(T_j,F_j)
\]

where `T` is page-treatment credit and `F` is complete-path-fit credit. The item row records both axes, the combined credit, structured rule IDs, evidence IDs, and a concise explanation. Explanation prose cannot alter the category or arithmetic.

Structure, cross-reference, missing-access, and source-subject rows project the corresponding current audit records. Multi-defect arrays use stable defect-ID ordering so repeated output is deterministic.

Aggregate dimension scores must be read from the calculation artifact, not reconstructed by averaging displayed item grades.
