"""Image forensics for detecting manipulated or altered images in documents."""
import logging
import numpy as np
from typing import Dict, List, Any, Optional
from PIL import Image
import io

try:
    import cv2
    from skimage import filters, feature
    from skimage.metrics import structural_similarity as ssim
    CV_AVAILABLE = True
except ImportError:
    CV_AVAILABLE = False

logger = logging.getLogger(__name__)


class ImageForensicsAnalyzer:
    """Detect image manipulation and alterations in document images."""

    def __init__(self):
        self.ela_threshold = 15  # Error Level Analysis threshold
        self.noise_variance_threshold = 0.02

    def analyze_image(self, image_data: bytes, filename: str = "") -> Dict[str, Any]:
        """
        Analyze an image for signs of manipulation.

        Args:
            image_data: Image bytes
            filename: Optional filename for context

        Returns:
            Dictionary with forensics results
        """
        if not CV_AVAILABLE:
            return {
                "analyzed": False,
                "error": "Image forensics libraries not available"
            }

        results = {
            "analyzed": True,
            "filename": filename,
            "manipulations_detected": False,
            "flags": [],
            "techniques_used": []
        }

        try:
            # Load image
            img = Image.open(io.BytesIO(image_data))
            img_array = np.array(img)

            # Convert to grayscale for analysis
            if len(img_array.shape) == 3:
                gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_array

            # Run forensics checks
            self._check_error_level_analysis(img, results)
            self._check_noise_analysis(gray, results)
            self._check_jpeg_artifacts(img_array, results)
            self._check_copy_move(gray, results)
            self._check_alignment_issues(gray, results)

            # Determine if manipulations were detected
            results["manipulations_detected"] = len(results["flags"]) > 0

        except Exception as e:
            logger.error(f"Error analyzing image {filename}: {e}")
            results["error"] = str(e)

        return results

    def _check_error_level_analysis(self, img: Image.Image, results: Dict):
        """
        Perform Error Level Analysis (ELA) to detect edited regions.
        Compressed images that have been edited will show different error levels.
        """
        try:
            results["techniques_used"].append("error_level_analysis")

            # Save at quality 95 and compare
            buffer1 = io.BytesIO()
            img.save(buffer1, format='JPEG', quality=95)
            buffer1.seek(0)

            resaved = Image.open(buffer1)

            # Calculate difference
            original = np.array(img).astype(np.float32)
            compressed = np.array(resaved).astype(np.float32)

            if original.shape == compressed.shape:
                diff = np.abs(original - compressed)

                # Analyze difference levels
                if len(diff.shape) == 3:
                    diff_gray = np.mean(diff, axis=2)
                else:
                    diff_gray = diff

                max_diff = np.max(diff_gray)
                mean_diff = np.mean(diff_gray)

                # Check for suspicious high-difference regions
                if max_diff > 50:
                    high_error_regions = np.sum(diff_gray > 30)
                    total_pixels = diff_gray.size

                    if high_error_regions / total_pixels > 0.01:  # More than 1% of pixels
                        results["flags"].append({
                            "type": "ela_anomaly",
                            "description": "Error Level Analysis detected potential editing",
                            "severity": "high",
                            "details": [
                                f"Maximum error level: {max_diff:.1f}",
                                f"Average error level: {mean_diff:.1f}",
                                f"High-error regions: {(high_error_regions/total_pixels)*100:.2f}% of image"
                            ]
                        })

        except Exception as e:
            logger.error(f"ELA check failed: {e}")

    def _check_noise_analysis(self, gray: np.ndarray, results: Dict):
        """
        Analyze noise patterns to detect inconsistencies.
        Edited regions often have different noise characteristics.
        """
        try:
            results["techniques_used"].append("noise_analysis")

            # Divide image into blocks and analyze noise variance
            h, w = gray.shape
            block_size = 64
            variances = []

            for i in range(0, h - block_size, block_size):
                for j in range(0, w - block_size, block_size):
                    block = gray[i:i+block_size, j:j+block_size]
                    # Apply high-pass filter to isolate noise
                    edges = filters.sobel(block)
                    variance = np.var(edges)
                    variances.append(variance)

            if len(variances) > 10:
                var_array = np.array(variances)
                variance_of_variance = np.var(var_array)

                # Suspicious if noise variance varies too much
                if variance_of_variance > self.noise_variance_threshold:
                    results["flags"].append({
                        "type": "inconsistent_noise",
                        "description": "Inconsistent noise patterns detected across image",
                        "severity": "medium",
                        "details": [
                            f"Noise variance inconsistency: {variance_of_variance:.4f}",
                            "May indicate copy-paste or splicing manipulation"
                        ]
                    })

        except Exception as e:
            logger.error(f"Noise analysis failed: {e}")

    def _check_jpeg_artifacts(self, img_array: np.ndarray, results: Dict):
        """
        Check for inconsistent JPEG compression artifacts.
        Re-compressed regions show different artifact patterns.
        """
        try:
            results["techniques_used"].append("jpeg_artifact_analysis")

            if len(img_array.shape) == 3:
                gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_array

            # Detect 8x8 grid patterns typical of JPEG
            h, w = gray.shape
            block_artifacts = []

            for i in range(0, h - 16, 8):
                for j in range(0, w - 16, 8):
                    # Check horizontal edges at 8-pixel intervals
                    edge_strength = np.abs(gray[i+8, j:j+8].astype(float) - gray[i+7, j:j+8].astype(float))
                    block_artifacts.append(np.mean(edge_strength))

            if len(block_artifacts) > 10:
                artifact_var = np.var(block_artifacts)

                # High variance suggests inconsistent compression
                if artifact_var > 100:
                    results["flags"].append({
                        "type": "jpeg_artifact_inconsistency",
                        "description": "Inconsistent JPEG compression artifacts detected",
                        "severity": "medium",
                        "details": [
                            f"Artifact pattern variance: {artifact_var:.1f}",
                            "Different regions may have been compressed at different times"
                        ]
                    })

        except Exception as e:
            logger.error(f"JPEG artifact check failed: {e}")

    def _check_copy_move(self, gray: np.ndarray, results: Dict):
        """
        Detect copy-move forgery where regions are duplicated within the image.
        """
        try:
            results["techniques_used"].append("copy_move_detection")

            # Use SIFT/ORB to detect similar regions
            orb = cv2.ORB_create(nfeatures=500)
            keypoints, descriptors = orb.detectAndCompute(gray, None)

            if descriptors is not None and len(descriptors) > 50:
                # Use brute force matcher to find similar regions
                bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
                matches = bf.knnMatch(descriptors, descriptors, k=10)

                # Count suspiciously similar regions (excluding self-matches)
                suspicious_matches = 0
                for match_group in matches:
                    if len(match_group) > 3:  # More than 3 very similar regions
                        # Check if matches are not self-matches
                        distances = [m.distance for m in match_group[1:]]  # Skip first (self)
                        if np.mean(distances) < 30:  # Very similar
                            suspicious_matches += 1

                if suspicious_matches > 10:
                    results["flags"].append({
                        "type": "copy_move_suspected",
                        "description": "Potential copy-move manipulation detected",
                        "severity": "high",
                        "details": [
                            f"Found {suspicious_matches} suspicious duplicate regions",
                            "Regions of the image may have been copied and pasted"
                        ]
                    })

        except Exception as e:
            logger.error(f"Copy-move check failed: {e}")

    def _check_alignment_issues(self, gray: np.ndarray, results: Dict):
        """
        Check for misaligned text/numbers that suggest copy-paste manipulation.
        Looks for inconsistent character spacing and baseline alignment.
        """
        try:
            results["techniques_used"].append("alignment_analysis")

            # Detect horizontal edges (text baselines)
            edges = cv2.Canny(gray, 50, 150)

            # Use Hough transform to find lines
            lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=100,
                                    minLineLength=30, maxLineGap=10)

            if lines is not None and len(lines) > 5:
                # Analyze line angles
                angles = []
                for line in lines:
                    x1, y1, x2, y2 = line[0]
                    if x2 != x1:  # Avoid division by zero
                        angle = np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi
                        # Focus on nearly horizontal lines (text baselines)
                        if -10 < angle < 10:
                            angles.append(angle)

                if len(angles) > 10:
                    angle_std = np.std(angles)

                    # High standard deviation suggests misaligned text
                    if angle_std > 2.0:
                        results["flags"].append({
                            "type": "alignment_inconsistency",
                            "description": "Text alignment inconsistencies detected",
                            "severity": "medium",
                            "details": [
                                f"Text baseline angle variance: {angle_std:.2f}°",
                                "Text or numbers may have been copied from different sources",
                                "Check for overlaid or replaced numbers in financial totals"
                            ]
                        })

        except Exception as e:
            logger.error(f"Alignment check failed: {e}")


# Global analyzer instance
_analyzer = None

def get_analyzer() -> ImageForensicsAnalyzer:
    """Get or create the global image forensics analyzer."""
    global _analyzer
    if _analyzer is None:
        _analyzer = ImageForensicsAnalyzer()
    return _analyzer
