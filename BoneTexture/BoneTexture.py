import csv
import logging
import os
import qt
import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
# Use segment statistics to compute good default parameters for texture modules.
import SegmentStatistics

import math  # for ceil
import VectorToScalarVolume # For extra widget, handling input vector/RGB images.

################################################################################
############################  Bone Texture #####################################
################################################################################


class BoneTexture(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "Bone Texture"
        self.parent.categories = ["Quantification"]
        self.parent.dependencies = []
        self.parent.contributors = ["Jean-Baptiste VIMORT (Kitware Inc.)"]
        self.parent.helpText = """
        This module is based on two texture analysis filters that are used to compute
        feature maps of N-Dimensional images using two well-known texture analysis methods.
        The two filters used in this module are itkCoocurrenceTextureFeaturesImageFilter
        (which computes textural features based on intensity-based co-occurrence matrices in
        the image) and itkRunLengthTextureFeaturesImageFilter (which computes textural
        features based on equally valued intensity clusters of different sizes or run lengths
        in the image). The output of this module is a vector image of the same size than the
        input that contains a multidimensional vector in each pixel/voxel. Filters can be configured
        based in the locality of the textural features (neighborhood size), offset directions
        for co-ocurrence and run length computation, the number of bins for the intensity
        histograms, the intensity range or the range of run lengths.
        """
        self.parent.acknowledgementText = """
        This work was supported by the National Institute of Health (NIH) National Institute for
        Dental and Craniofacial Research (NIDCR) R01EB021391 (Textural Biomarkers of Arthritis for
        the Subchondral Bone in the Temporomandibular Joint)
        """


class TableCopyFilter(qt.QWidget):
    def eventFilter(self, source, event):
        if event.type() == qt.QEvent.KeyPress and event.matches(qt.QKeySequence.Copy):
            self.copySelected(source)
            return True
        return False

    def copySelected(self, table):
        selection = table.selectedIndexes()

        if selection:
            rows = sorted(set(index.row() for index in selection))
            cols = sorted(set(index.column() for index in selection))

            # allow looking up index data by coordinate
            data = {(index.row(), index.column()): index.data() for index in selection}

            # fetch a full grid of rows x columns. missing (unselected) values are ''
            parts = [[data.get((row, col), '') for col in cols] for row in rows]

            # join table into tsv-formatted text
            text = '\n'.join('\t'.join(part) for part in parts)

            slicer.app.clipboard().setText(text)

################################################################################
##########################  Bone Texture Widget ################################
################################################################################


class BoneTextureWidget(ScriptedLoadableModuleWidget):

    # ************************************************************************ #
    # -------------------------- Initialisation ------------------------------ #
    # ************************************************************************ #

    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        self.logic = BoneTextureLogic(self)

        self.CFeatures = ["energy", "entropy",
                          "correlation", "inverseDifferenceMoment",
                          "inertia", "clusterShade",
                          "clusterProminence", "haralickCorrelation"]
        self.RLFeatures = ["shortRunEmphasis", "longRunEmphasis",
                           "greyLevelNonuniformity", "runLengthNonuniformity",
                           "lowGreyLevelRunEmphasis", "highGreyLevelRunEmphasis",
                           "shortRunLowGreyLevelEmphasis", "shortRunHighGreyLevelEmphasis",
                           "longRunLowGreyLevelEmphasis", "longRunHighGreyLevelEmphasis"]
        self.BMFeatures = ["BVTV", "TbTh", "TbSp", "TbN", "BSBV"]


    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        logging.debug("-----  Bone Texture widget setup -----")
        self.moduleName = 'BoneTexture'
        scriptedModulesPath = eval('slicer.modules.%s.path' % self.moduleName.lower())
        scriptedModulesPath = os.path.dirname(scriptedModulesPath)

        # - Init parameters. - #
        # TODO (EASY): a parameter node should be maintained instead of these dictionaries. - #

        self.GLCMFeaturesValueDict = {}
        self.GLCMFeaturesValueDict["insideMask"] = 1
        self.GLCMFeaturesValueDict["binNumber"] = 10
        self.GLCMFeaturesValueDict["pixelIntensityMin"] = 0
        self.GLCMFeaturesValueDict["pixelIntensityMax"] = 4000
        self.GLCMFeaturesValueDict["neighborhoodRadius"] = 4
        self.GLRLMFeaturesValueDict = {}
        self.GLRLMFeaturesValueDict["insideMask"] = 1
        self.GLRLMFeaturesValueDict["binNumber"] = 10
        self.GLRLMFeaturesValueDict["pixelIntensityMin"] = 0
        self.GLRLMFeaturesValueDict["pixelIntensityMax"] = 4000
        self.GLRLMFeaturesValueDict["neighborhoodRadius"] = 4
        self.GLRLMFeaturesValueDict["distanceMin"] = 0.00
        self.GLRLMFeaturesValueDict["distanceMax"] = 1.00
        self.BMFeaturesValueDict = {}
        self.BMFeaturesValueDict["threshold"] = 1
        self.BMFeaturesValueDict["neighborhoodRadius"] = 4

        # -------------------------------------------------------------------- #
        # ----------------- Definition of the UI interface ------------------- #
        # -------------------------------------------------------------------- #

        # -------------------- Loading of the .ui file ----------------------- #

        loader = qt.QUiLoader()
        path = os.path.join(scriptedModulesPath, 'Resources', 'UI', '%s.ui' % self.moduleName)
        qfile = qt.QFile(path)
        qfile.open(qt.QFile.ReadOnly)
        widget = loader.load(qfile, self.parent)
        self.layout = self.parent.layout()
        self.widget = widget
        self.layout.addWidget(widget)

        # ---------------- Input Data Collapsible Button --------------------- #

        self.inputDataCollapsibleButton = self.logic.get("InputDataCollapsibleButton")
        self.inputDataVerticalLayout = self.logic.get("InputDataVerticalLayout")
        self.singleCaseGroupBox = self.logic.get("SingleCaseGroupBox")
        self.inputScanMRMLNodeComboBox = self.logic.get("InputScanMRMLNodeComboBox")
        self.inputScanMRMLNodeComboBox.setMRMLScene(slicer.mrmlScene)
        self.inputSegmentationMRMLNodeComboBox = self.logic.get("InputSegmentationMRMLNodeComboBox")
        self.inputSegmentationMRMLNodeComboBox.setMRMLScene(slicer.mrmlScene)
        # Add a python widget from core slicer scripted module: VectorToScalarModule
        # It works fine, but that module should be written in c++ to be truly reusable with qtdesigner,
        self.vectorToScalarVolumeGroupBox = qt.QGroupBox(self.inputDataCollapsibleButton)
        self.vectorToScalarVolumeGroupBox.setTitle("Conversion: Vector Input Scan to Scalar")
        self.vectorToScalarVolumeLayout = qt.QVBoxLayout(self.vectorToScalarVolumeGroupBox)
        self.vectorToScalarVolumeConversionWidget = VectorToScalarVolume.VectorToScalarVolumeConversionMethodWidget()
        self.vectorToScalarVolumePushButton = qt.QPushButton(self.vectorToScalarVolumeGroupBox)
        self.vectorToScalarVolumePushButton.setText("Convert input scan to scalar")
        self.vectorToScalarVolumeLayout.addWidget(self.vectorToScalarVolumeConversionWidget)
        self.vectorToScalarVolumeLayout.addWidget(self.vectorToScalarVolumePushButton)
        self.inputDataVerticalLayout.addWidget(self.vectorToScalarVolumeGroupBox)
        vectorToScalarIndex = self.vectorToScalarVolumeConversionWidget.methodSelectorComboBox.findData(
            VectorToScalarVolume.VectorToScalarVolumeLogic.LUMINANCE)
        self.vectorToScalarVolumeConversionWidget.methodSelectorComboBox.setCurrentIndex(vectorToScalarIndex)
        self.vectorToScalarVolumeGroupBox.enabled = False

        # ---------------- Computation Collapsible Button -------------------- #

        self.computationCollapsibleButton = self.logic.get("ComputationCollapsibleButton")
        self.featureChoiceCollapsibleGroupBox = self.logic.get("FeatureChoiceCollapsibleGroupBox")
        self.gLCMFeaturesCheckBox = self.logic.get("GLCMFeaturesCheckBox")
        self.gLRLMFeaturesCheckBox = self.logic.get("GLRLMFeaturesCheckBox")
        self.bMFeaturesCheckBox = self.logic.get("BMFeaturesCheckBox")
        self.computeFeaturesPushButton = self.logic.get("ComputeFeaturesPushButton")
        self.computeColormapsPushButton = self.logic.get("ComputeColormapsPushButton")
        self.computeParametersBasedOnInputs = self.logic.get("ComputeParametersBasedOnInputsButton")
        self.GLCMparametersCollapsibleGroupBox = self.logic.get("GLCMParametersCollapsibleGroupBox")
        self.GLCMinsideMaskValueSpinBox = self.logic.get("GLCMInsideMaskValueSpinBox")
        self.GLCMnumberOfBinsSpinBox = self.logic.get("GLCMNumberOfBinsSpinBox")
        self.GLCMminVoxelIntensitySpinBox = self.logic.get("GLCMMinVoxelIntensitySpinBox")
        self.GLCMmaxVoxelIntensitySpinBox = self.logic.get("GLCMMaxVoxelIntensitySpinBox")
        self.GLCMneighborhoodRadiusSpinBox = self.logic.get("GLCMNeighborhoodRadiusSpinBox")
        self.GLRLMparametersCollapsibleGroupBox = self.logic.get("GLRLMParametersCollapsibleGroupBox")
        self.GLRLMinsideMaskValueSpinBox = self.logic.get("GLRLMInsideMaskValueSpinBox")
        self.GLRLMnumberOfBinsSpinBox = self.logic.get("GLRLMNumberOfBinsSpinBox")
        self.GLRLMminVoxelIntensitySpinBox = self.logic.get("GLRLMMinVoxelIntensitySpinBox")
        self.GLRLMmaxVoxelIntensitySpinBox = self.logic.get("GLRLMMaxVoxelIntensitySpinBox")
        self.GLRLMminDistanceSpinBox = self.logic.get("GLRLMMinDistanceSpinBox")
        self.GLRLMmaxDistanceSpinBox = self.logic.get("GLRLMMaxDistanceSpinBox")
        self.GLRLMneighborhoodRadiusSpinBox = self.logic.get("GLRLMNeighborhoodRadiusSpinBox")
        self.bMparametersCollapsibleGroupBox = self.logic.get("BMParametersCollapsibleGroupBox")
        self.BMthresholdSpinBox = self.logic.get("BMThresholdSpinBox")
        self.BMneighborhoodRadiusSpinBox = self.logic.get("BMNeighborhoodRadiusSpinBox")

        # ----------------- Results Collapsible Button ----------------------- #

        self.resultsCollapsibleButton = self.logic.get("ResultsCollapsibleButton")
        self.featureSetMRMLNodeComboBox = self.logic.get("featureSetMRMLNodeComboBox")
        self.featureSetMRMLNodeComboBox.setMRMLScene(slicer.mrmlScene)
        self.featureComboBox = self.logic.get("featureComboBox")
        self.displayColormapsCollapsibleGroupBox = self.logic.get("DisplayColormapsCollapsibleGroupBox")
        self.displayFeaturesTableWidget = self.logic.get("displayFeaturesTableWidget")
        self.SaveTablePushButton = self.logic.get("SaveTablePushButton")
        self.CSVPathLineEdit = self.logic.get("CSVPathLineEdit")

        # -------------------------------------------------------------------- #
        # ---------------------------- Connections --------------------------- #
        # -------------------------------------------------------------------- #

        # ------------------------- Input Images ----------------------------- #
        self.inputScanMRMLNodeComboBox.connect("currentNodeChanged(vtkMRMLNode*)", self.onInputScanChanged)

        self.vectorToScalarVolumeConversionWidget.methodSelectorComboBox.connect(
            'currentIndexChanged(int)',
            lambda currentIndex:
            self.vectorToScalarVolumeConversionWidget.setGuiBasedOnOptions(
                self.vectorToScalarVolumeConversionWidget.methodSelectorComboBox.itemData(currentIndex),
                self.inputScanMRMLNodeComboBox.currentNode())
        )
        self.vectorToScalarVolumePushButton.connect('clicked()', self.onVectorToScalarVolumePushButtonClicked)
        # ---------------- Computation Collapsible Button --------------------- #

        self.GLCMinsideMaskValueSpinBox.connect('valueChanged(int)',
                                                lambda: self.onGLCMFeaturesValueDictModified("insideMask", self.GLCMinsideMaskValueSpinBox.value))
        self.GLCMnumberOfBinsSpinBox.connect('valueChanged(int)',
                                             lambda: self.onGLCMFeaturesValueDictModified("binNumber", self.GLCMnumberOfBinsSpinBox.value))
        self.GLCMminVoxelIntensitySpinBox.connect('valueChanged(int)',
                                                  lambda: self.onGLCMFeaturesValueDictModified("pixelIntensityMin", self.GLCMminVoxelIntensitySpinBox.value))
        self.GLCMmaxVoxelIntensitySpinBox.connect('valueChanged(int)',
                                                  lambda: self.onGLCMFeaturesValueDictModified("pixelIntensityMax", self.GLCMmaxVoxelIntensitySpinBox.value))
        self.GLCMneighborhoodRadiusSpinBox.connect('valueChanged(int)',
                                                   lambda: self.onGLCMFeaturesValueDictModified("neighborhoodRadius", self.GLCMneighborhoodRadiusSpinBox.value))
        self.GLRLMinsideMaskValueSpinBox.connect('valueChanged(int)',
                                                 lambda: self.onGLRLMFeaturesValueDictModified("insideMask", self.GLRLMinsideMaskValueSpinBox.value))
        self.GLRLMnumberOfBinsSpinBox.connect('valueChanged(int)',
                                              lambda: self.onGLRLMFeaturesValueDictModified("binNumber", self.GLRLMnumberOfBinsSpinBox.value))
        self.GLRLMminVoxelIntensitySpinBox.connect('valueChanged(int)',
                                                   lambda: self.onGLRLMFeaturesValueDictModified("pixelIntensityMin", self.GLRLMminVoxelIntensitySpinBox.value))
        self.GLRLMmaxVoxelIntensitySpinBox.connect('valueChanged(int)',
                                                   lambda: self.onGLRLMFeaturesValueDictModified("pixelIntensityMax", self.GLRLMmaxVoxelIntensitySpinBox.value))
        self.GLRLMminDistanceSpinBox.connect('valueChanged(double)',
                                             lambda: self.onGLRLMFeaturesValueDictModified("distanceMin", self.GLRLMminDistanceSpinBox.value))
        self.GLRLMmaxDistanceSpinBox.connect('valueChanged(double)',
                                             lambda: self.onGLRLMFeaturesValueDictModified("distanceMax", self.GLRLMmaxDistanceSpinBox.value))
        self.GLRLMneighborhoodRadiusSpinBox.connect('valueChanged(int)',
                                                    lambda: self.onGLRLMFeaturesValueDictModified("neighborhoodRadius", self.GLRLMneighborhoodRadiusSpinBox.value))
        self.BMthresholdSpinBox.connect('valueChanged(int)',
                                        lambda: self.onBMFeaturesValueDictModified("threshold", self.BMthresholdSpinBox.value))
        self.BMneighborhoodRadiusSpinBox.connect('valueChanged(int)',
                                                 lambda: self.onBMFeaturesValueDictModified("neighborhoodRadius", self.BMneighborhoodRadiusSpinBox.value))

        # ----------- Compute Parameters Based on Inputs Button -------------- #
        self.computeParametersBasedOnInputs.connect('clicked()', self.onComputeParametersBasedOnInputs)

        # ---------------- Computation Collapsible Button -------------------- #
        self.computeFeaturesPushButton.connect('clicked()', self.onComputeFeatures)
        self.computeColormapsPushButton.connect('clicked()', self.onComputeColormaps)

        # ----------------- Results Collapsible Button ----------------------- #

        self.featureSetMRMLNodeComboBox.connect("currentNodeChanged(vtkMRMLNode*)", self.onFeatureSetChanged)
        self.featureComboBox.connect("currentIndexChanged(int)", self.onFeatureChanged)
        self.SaveTablePushButton.connect('clicked()', self.onSaveTable)
        copy_filter = TableCopyFilter(self.displayFeaturesTableWidget)
        self.displayFeaturesTableWidget.installEventFilter(copy_filter)

        # -------------------------------------------------------------------- #
        # -------------------------- Initialisation -------------------------- #
        # -------------------------------------------------------------------- #

        # ******************************************************************** #
        # ----------------------- Algorithm ---------------------------------- #
        # ******************************************************************** #

        # ---------------- Input Data Collapsible Button --------------------- #

    def onInputScanChanged(self):
        """ Check if input is vector image, and allow conversion enabling VectorToScalarVolume widget """
        inputScan = self.inputScanMRMLNodeComboBox.currentNode()
        if inputScan is None:
            self.vectorToScalarVolumeGroupBox.enabled = False
            return
        if inputScan.IsTypeOf('vtkMRMLVectorVolumeNode'):
            self.vectorToScalarVolumeGroupBox.enabled = True
        else:
            self.vectorToScalarVolumeGroupBox.enabled = False

    def onVectorToScalarVolumePushButtonClicked(self):
        """
        Convert current input VectorVolume to a ScalarVolume.
        And set that ScalarVolume as the new input.
        """
        # create and add output node to scene (hide this selection from user)
        inputVolumeNode = self.inputScanMRMLNodeComboBox.currentNode()
        conversionMethod = self.vectorToScalarVolumeConversionWidget.conversionMethod()
        componentToExtract = self.vectorToScalarVolumeConversionWidget.componentToExtract()

        inputName = self.inputScanMRMLNodeComboBox.currentNode().GetName()
        methodName = '_ToScalarMethod'
        outputName = inputName + methodName + conversionMethod
        if conversionMethod == VectorToScalarVolume.VectorToScalarVolumeLogic.SINGLE_COMPONENT:
            outputName += str(componentToExtract)
        outputVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", slicer.mrmlScene.GetUniqueNameByString(outputName))
        # run conversion
        success = self.logic.convertInputVectorToScalarVolume(inputVolumeNode,
                                                              outputVolumeNode,
                                                              conversionMethod,
                                                              componentToExtract)
        if success:
            selectionNode = slicer.app.applicationLogic().GetSelectionNode()
            selectionNode.SetReferenceActiveVolumeID(outputVolumeNode.GetID())
            slicer.app.applicationLogic().PropagateVolumeSelection(0)

            # set the output as the new input for this module.
            self.inputScanMRMLNodeComboBox.setCurrentNode(outputVolumeNode)
        else:
            slicer.mrmlScene.RemoveNode(outputVolumeNode)


    def onGLCMFeaturesValueDictModified(self, key, value):
        self.GLCMFeaturesValueDict[key] = value

    def onGLRLMFeaturesValueDictModified(self, key, value):
        self.GLRLMFeaturesValueDict[key] = value

    def onBMFeaturesValueDictModified(self, key, value):
        self.BMFeaturesValueDict[key] = value

        # ---------------- Computation Collapsible Button -------------------- #

    def onComputeParametersBasedOnInputs(self):
        inputScan = self.inputScanMRMLNodeComboBox.currentNode()
        inputSegmentation = self.inputSegmentationMRMLNodeComboBox.currentNode()
        isValid = self.logic.inputDataVerification(inputScan, inputSegmentation)
        if isValid is False:
            return

        minIntensityValue, maxIntensityValue = self.logic.computeLabelStatistics(inputScan, inputSegmentation)
        numBins = self.logic.computeBinsBasedOnIntensityRange(minIntensityValue, maxIntensityValue)

        self.GLCMnumberOfBinsSpinBox.value = numBins
        self.GLCMminVoxelIntensitySpinBox.value = minIntensityValue
        self.GLCMmaxVoxelIntensitySpinBox.value = maxIntensityValue
        self.GLRLMnumberOfBinsSpinBox.value = numBins
        self.GLRLMminVoxelIntensitySpinBox.value = minIntensityValue
        self.GLRLMmaxVoxelIntensitySpinBox.value = maxIntensityValue

    def onComputeFeatures(self):
        # This will run async, and populate self.logic.featuresXXX
        self.logic.computeFeatures(self.inputScanMRMLNodeComboBox.currentNode(),
                                   self.inputSegmentationMRMLNodeComboBox.currentNode(),
                                   self.gLCMFeaturesCheckBox.isChecked(),
                                   self.gLRLMFeaturesCheckBox.isChecked(),
                                   self.bMFeaturesCheckBox.isChecked(),
                                   self.GLCMFeaturesValueDict,
                                   self.GLRLMFeaturesValueDict,
                                   self.BMFeaturesValueDict)

    def onDisplayFeatures(self):
        if self.logic.featuresGLCM is not None:
            for i in range(8):
                self.displayFeaturesTableWidget.item(i,1).setText(self.logic.featuresGLCM[i])

        if self.logic.featuresGLRLM is not None:
            for i in range(10):
                self.displayFeaturesTableWidget.item(i, 3).setText(self.logic.featuresGLRLM[i])

        if self.logic.featuresBM is not None:
            for i in range(5):
                self.displayFeaturesTableWidget.item(i, 5).setText(self.logic.featuresBM[i])

    def onComputeColormaps(self):
        self.logic.computeColormaps(self.inputScanMRMLNodeComboBox.currentNode(),
                                    self.inputSegmentationMRMLNodeComboBox.currentNode(),
                                    self.gLCMFeaturesCheckBox.isChecked(),
                                    self.gLRLMFeaturesCheckBox.isChecked(),
                                    self.bMFeaturesCheckBox.isChecked(),
                                    self.GLCMFeaturesValueDict,
                                    self.GLRLMFeaturesValueDict,
                                    self.BMFeaturesValueDict)

        # ----------------- Results Collapsible Button ----------------------- #

    def onFeatureSetChanged(self, node):

        self.featureComboBox.clear()

        if node is None:
            return

        # Set the festureSet displayed in Slicer to the selected module
        selectionNode = slicer.app.applicationLogic().GetSelectionNode()
        selectionNode.SetReferenceActiveVolumeID(node.GetID())
        mode = slicer.vtkMRMLApplicationLogic.BackgroundLayer
        applicationLogic = slicer.app.applicationLogic()
        applicationLogic.PropagateVolumeSelection(mode, 0)

        # Set the good feature names in the featureCombobox
        if node.GetDisplayNode().GetInputImageData().GetNumberOfScalarComponents() == 8:
            self.featureComboBox.addItems(self.CFeatures)
        elif node.GetDisplayNode().GetInputImageData().GetNumberOfScalarComponents() == 10:
            self.featureComboBox.addItems(self.RLFeatures)
        elif node.GetDisplayNode().GetInputImageData().GetNumberOfScalarComponents() == 5:
            self.featureComboBox.addItems(self.BMFeatures)

    def onFeatureChanged(self, index):
        if self.featureSetMRMLNodeComboBox.currentNode():
            # Change the feature displayed to the one wanted by the user
            self.featureSetMRMLNodeComboBox.currentNode().GetDisplayNode().SetDiffusionComponent(index)

    def onSaveTable(self):
        self.logic.SaveTableAsCSV(self.displayFeaturesTableWidget,self.CSVPathLineEdit.currentPath)

    def cleanup(self):
        pass


################################################################################
############################  Bone Texture Logic ###############################
################################################################################
class BoneTextureLogic(ScriptedLoadableModuleLogic, VTKObservationMixin):
    # ************************************************************************ #
    # ----------------------- Initialisation --------------------------------- #
    # ************************************************************************ #

    def __init__(self, interface):
        logging.debug("----- Bone Texture logic init -----")
        ScriptedLoadableModuleLogic.__init__(self)
        VTKObservationMixin.__init__(self)
        self.interface = interface
        # Outputs:
        self.featuresGLCM = None
        self.featuresGLRLM = None
        self.featuresBM = None

    def __del__(self):
        self.removeObservers()

    def isClose(self, a, b, rel_tol=0.0, abs_tol=0.0):
        for i in range(len(a)):
            if not (abs(a[i] - b[i]) <= max(rel_tol * max(abs(a[i]), abs(b[i])), abs_tol)):
                return False
        return True

    def computeLabelStatistics(self, inputScan, inputLabelMapNode):
        """ Use slicer core module to get the min/max intensity value inside the mask.
        Returns tuple (min, max) with intensity values inside the mask. """
        # Export lapel map node into a segmentation node
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(inputLabelMapNode, segmentationNode)

        # Compute statistics (may take time)
        segStatLogic = SegmentStatistics.SegmentStatisticsLogic()
        segStatLogic.getParameterNode().SetParameter("Segmentation", segmentationNode.GetID())
        segStatLogic.getParameterNode().SetParameter("ScalarVolume", inputScan.GetID())

        # Disable all plugins
        for plugin in segStatLogic.plugins:
          pluginName = plugin.__class__.__name__
          segStatLogic.getParameterNode().SetParameter(f"{pluginName}.enabled", str(False))

        # Explicitly enable ScalarVolumeSegmentStatistics
        segStatLogic.getParameterNode().SetParameter("ScalarVolumeSegmentStatisticsPlugin.enabled", str(True))
        segStatLogic.computeStatistics()
        stats = segStatLogic.getStatistics()

        # Remove temporary segmentation node
        slicer.mrmlScene.RemoveNode(segmentationNode)

        segmentId = stats["SegmentIDs"][0]
        minIntensityValue = stats[segmentId, "ScalarVolumeSegmentStatisticsPlugin.min"]
        maxIntensityValue = stats[segmentId, "ScalarVolumeSegmentStatisticsPlugin.max"]

        return minIntensityValue, maxIntensityValue

    def computeBinsBasedOnIntensityRange(self, minIntensityValue, maxIntensityValue):
        """ Compute number of bins based on the intensity range min/max.
        The formula is ad-hoc, and add 100 bins for each 1000 value difference between min and max.
        Example: min = -500,  max = 3000, numBins = 400
        The minimum number of bins is 100, indepedently of the input.
        Returns integer number of bins.
        """
        numBins = 100 * int(math.ceil(abs(maxIntensityValue - minIntensityValue)/1000.0))
        return numBins


    # ************************************************************************ #
    # ------------------------ Algorithm ------------------------------------- #
    # ************************************************************************ #

    # ----------- Useful functions to access the .ui file elements ----------- #

    def get(self, objectName):
        return self.findWidget(self.interface.widget, objectName)

    def findWidget(self, widget, objectName):
        if widget.objectName == objectName:
            return widget
        else:
            for w in widget.children():
                resulting_widget = self.findWidget(w, objectName)
                if resulting_widget:
                    return resulting_widget
            return None

    # ------- Test to ensure that the input data exist and are conform ------- #

    def inputDataVerification(self, inputScan, inputSegmentation):
        if not(inputScan):
            slicer.util.warningDisplay("Please specify an input scan")
            return False
        else:
            if inputScan.IsTypeOf('vtkMRMLVectorVolumeNode'):
                slicer.util.warningDisplay("The input scan has a vector pixel type, please transform it to a scalar type first.")
                return False

        if inputScan and inputSegmentation:
            if inputScan.GetImageData().GetDimensions() != inputSegmentation.GetImageData().GetDimensions():
                slicer.util.warningDisplay("The input scan and the input segmentation must be the same size")
                return False
            if not self.isClose(inputScan.GetSpacing(), inputSegmentation.GetSpacing(), 0.0, 1e-04) or \
                    not self.isClose(inputScan.GetOrigin(), inputSegmentation.GetOrigin(), 0.0, 1e-04):
                slicer.util.warningDisplay("The input scan and the input segmentation must overlap: same origin, spacing and orientation")
                return False
        return True

    # ---------------- Convert Vector Input to Scalar ---------------------- #
    def convertInputVectorToScalarVolume(self, inputScan, outputScalarVolume, conversionMethod, componentToExtract):
        externalLogic = VectorToScalarVolume.VectorToScalarVolumeLogic()
        # externalLogic.run performs the validation of parameters.
        return externalLogic.runWithVariables(inputScan, outputScalarVolume, conversionMethod, componentToExtract)

    # ---------------- Computation of the wanted features---------------------- #

    def computeFeatures(self,
                        inputScan,
                        inputSegmentation,
                        computeGLCMFeatures,
                        computeGLRLMFeatures,
                        computeBMFeatures,
                        GLCMFeaturesValueDict,
                        GLRLMFeaturesValueDict,
                        BMFeaturesValueDict):

        if not (self.inputDataVerification(inputScan, inputSegmentation)):
            return
        if not (computeGLCMFeatures or computeGLRLMFeatures or computeBMFeatures):
            slicer.util.warningDisplay("Please select at least one type of features to compute")
            return

        # Create the CLInodes, and observe them for async logic
        if computeGLCMFeatures:
            logging.info('Computing GLCM Features ...')
            _module = slicer.modules.computeglcmfeatures
            GLCMParameters = dict(GLCMFeaturesValueDict)
            GLCMParameters["inputVolume"] = inputScan
            GLCMParameters["inputMask"] = inputSegmentation
            GLCMNode = slicer.cli.createNode(_module, GLCMParameters)
            self.addObserver(GLCMNode, slicer.vtkMRMLCommandLineModuleNode().StatusModifiedEvent, self.onGLCMNodeModified)
            GLCMNode = slicer.cli.run(_module, node=GLCMNode, parameters=GLCMParameters, wait_for_completion=False)

        if computeGLRLMFeatures:
            logging.info('Computing GLRLM Features ...')
            _module = slicer.modules.computeglrlmfeatures
            GLRLMParameters = dict(GLRLMFeaturesValueDict)
            GLRLMParameters["inputVolume"] = inputScan
            GLRLMParameters["inputMask"] = inputSegmentation
            GLRLMNode = slicer.cli.createNode(_module, GLRLMParameters)
            self.addObserver(GLRLMNode, slicer.vtkMRMLCommandLineModuleNode().StatusModifiedEvent, self.onGLRLMNodeModified)
            # self.GLRLMNodeObserver = GLRLMNode.AddObserver(slicer.vtkMRMLCommandLineModuleNode().StatusModifiedEvent, self.onGLRLMNodeModified)
            GLRLMNode = slicer.cli.run(_module, node=GLRLMNode, parameters=GLRLMParameters, wait_for_completion=False)

        if computeBMFeatures:
            logging.info('Computing BM Features ...')
            _module = slicer.modules.computebmfeatures
            BMParameters = dict(BMFeaturesValueDict)
            BMParameters["inputVolume"] = inputScan
            BMParameters["inputMask"] = inputSegmentation
            BMNode = slicer.cli.createNode(_module, BMParameters)
            self.addObserver(BMNode, slicer.vtkMRMLCommandLineModuleNode().StatusModifiedEvent, self.onBMNodeModified)
            BMNode = slicer.cli.run(_module, node=BMNode, parameters=BMParameters, wait_for_completion=False)

    def onGLCMNodeModified(self, cliNode, event):
        if not cliNode.IsBusy():
          self.removeObservers(self.onGLCMNodeModified)
          logging.info('GLCM status: %s' % cliNode.GetStatusString())
          if cliNode.GetStatusString() == 'Completed':
            self.featuresGLCM = list(map(float, cliNode.GetParameterValue(2, 0).split(",")))
            if self.interface is not None:
                self.interface.onDisplayFeatures()

    def onGLRLMNodeModified(self, cliNode, event):
        if not cliNode.IsBusy():
          self.removeObservers(self.onGLRLMNodeModified)
          logging.info('GLRLM status: %s' % cliNode.GetStatusString())
          if cliNode.GetStatusString() == 'Completed':
            self.featuresGLRLM = list(map(float, cliNode.GetParameterValue(2, 0).split(",")))
            if self.interface is not None:
                self.interface.onDisplayFeatures()

    def onBMNodeModified(self, cliNode, event):
        if not cliNode.IsBusy():
          self.removeObservers(self.onBMNodeModified)
          logging.info('BM status: %s' % cliNode.GetStatusString())
          if cliNode.GetStatusString() == 'Completed':
            self.featuresBM = list(map(float, cliNode.GetParameterValue(2, 0).split(",")))
            if self.interface is not None:
                self.interface.onDisplayFeatures()

    # def computeSingleFeatureSet(self,
    #                            inputScan,
    #                            inputSegmentation,
    #                            CLIname,
    #                            valueDict):
    #     parameters = dict(valueDict)
    #     parameters["inputVolume"] = inputScan
    #     parameters["inputMask"] = inputSegmentation
    #     CLI = slicer.cli.run(CLIname,
    #                          None,
    #                          parameters,
    #                          wait_for_completion=True)
    #     return list(map(float, CLI.GetParameterValue(2, 0).split(",")))

    # --------------- Computation of the wanted colormaps --------------------- #

    def computeColormaps(self,
                         inputScan,
                         inputSegmentation,
                         computeGLCMFeatures,
                         computeGLRLMFeatures,
                         computeBMFeatures,
                         GLCMFeaturesValueDict,
                         GLRLMFeaturesValueDict,
                         BMFeaturesValueDict):

        if not (self.inputDataVerification(inputScan, inputSegmentation)):
            return
        if not (computeGLCMFeatures or computeGLRLMFeatures or computeBMFeatures):
            slicer.util.warningDisplay("Please select at least one type of features to compute")
            return

        if computeGLCMFeatures:
            self.computeSingleColormap(inputScan,
                                       inputSegmentation,
                                       slicer.modules.computeglcmfeaturemaps,
                                       GLCMFeaturesValueDict,
                                       "GLCM_ColorMaps")

        if computeGLRLMFeatures:
            self.computeSingleColormap(inputScan,
                                       inputSegmentation,
                                       slicer.modules.computeglrlmfeaturemaps,
                                       GLRLMFeaturesValueDict,
                                       "GLRLM_ColorMaps")

        if computeBMFeatures:
            self.computeSingleColormap(inputScan,
                                       inputSegmentation,
                                       slicer.modules.computebmfeaturemaps,
                                       BMFeaturesValueDict,
                                       "BM_ColorMaps")

    def computeSingleColormap(self,
                              inputScan,
                              inputSegmentation,
                              CLIname,
                              valueDict,
                              outputName):
        parameters = dict(valueDict)
        parameters["inputVolume"] = inputScan
        parameters["inputMask"] = inputSegmentation
        volumeNode = slicer.vtkMRMLDiffusionWeightedVolumeNode()
        slicer.mrmlScene.AddNode(volumeNode)
        displayNode = slicer.vtkMRMLDiffusionWeightedVolumeDisplayNode()
        slicer.mrmlScene.AddNode(displayNode)
        colorNode = slicer.util.getNode('Rainbow')
        displayNode.SetAndObserveColorNodeID(colorNode.GetID())
        volumeNode.SetAndObserveDisplayNodeID(displayNode.GetID())
        volumeNode.SetName(outputName)
        parameters["outputVolume"] = volumeNode
        slicer.cli.run(CLIname,
                       None,
                       parameters,
                       wait_for_completion=False)

    def SaveTableAsCSV(self,
                       table,
                       fileName):
        if fileName is None:
            slicer.util.warningDisplay("Please specify an output file")
        if (not (fileName.endswith(".csv"))):
            slicer.util.warningDisplay("The output file must be a csv file")
        file = open(fileName, 'w')
        cw = csv.writer(file, delimiter=',')

        for j in range(6):
            row = []
            for i in range(10):
                if table.item(i, j):
                    row.append(table.item(i, j).text())
            cw.writerow(row)
        file.close()

################################################################################
###########################  Bone Texture Test #################################
################################################################################


class BoneTextureTest(ScriptedLoadableModuleTest):
    # ************************************************************************ #
    # -------------------------- Initialisation ------------------------------ #
    # ************************************************************************ #

    def setUp(self):
        logging.debug("----- Bone Texture test setup -----")
        # reset the state - clear scene
        self.delayDisplay("Clear the scene")
        slicer.mrmlScene.Clear(0)

        # ******************************************************************** #
        # -------------------- Testing of Bone Texture ----------------------- #
        # ******************************************************************** #

    def runTest(self):
        self.setUp()
        self.test_BoneTexture1()

    def test_BoneTexture1(self):
        self.delayDisplay("Starting the test")
